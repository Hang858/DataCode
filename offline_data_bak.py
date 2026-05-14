import os
import sys
import argparse
import pandas as pd
import re
import shutil
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from collections import Counter, defaultdict
import name  # 导入姓氏模块

# 全局配置参数
LOG_FILE = "old.log"                  # 已处理文件记录
PRIVATE_LOG = "private.log"           # 详细日志文件
UNPROCESSED_FOLDER = "未处理"
FOLDER_TO_PROCESS = "test"
SUPPORTED_EXTENSIONS = {'txt', 'xls', 'xlsx', 'csv'}  # 新增CSV支持
BATCH_SIZE = 1000                     # 每批插入的记录数
UNPROCESSED_THRESHOLD = 0.8           # 未处理行比例阈值（80%）
NAME_DUPLICATE_THRESHOLD = 0.8        # 姓名列重复率阈值（80%）

# 数据库配置
DB_CONFIG = {
    "host": "192.168.1.40",
    "database": "offline",
    "user": "root",
    "password": "MyPass123!",
    "auth_plugin": "caching_sha2_password",
    "connect_timeout": 30,
    "buffered": True
}

# 姓名黑名单
BLACKLIST_NAMES = {'真名','中国人','用户名','有限公司','中国','代收本金','代收利息','单元','公积金','先生', '女士', '小姐', '同志', '部门', '团队', '负责人', '联系人'}

# 地区关键词列表（按长度降序排序，确保长关键词优先匹配）
LOCATION_KEYWORDS = {'省', '市', '区', '县', '乡', '镇', '村', '街道', '地区', '自治州', '盟'}
LOCATION_KEYWORDS_SORTED = sorted(LOCATION_KEYWORDS, key=lambda x: -len(x))  # 按长度降序

# 身份证校验码权重
ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECKSUM = {0: '1', 1: '0', 2: 'X', 3: '9', 4: '8', 5: '7', 6: '6', 7: '5', 8: '4', 9: '3', 10: '2'}



# 新增：逐行验证函数
def validate_phone(phone_str):
    """验证手机号"""
    phone_pattern = re.compile(r'^1[3-9]\d{9}$')
    return phone_pattern.match(phone_str.strip()) is not None

def validate_name(name_str, skip_location_check=False):
    """验证姓名（可选择是否跳过地区关键词检查）"""
    if not name_str:
        return False
    if name_str in BLACKLIST_NAMES:
        return False
    if len(name_str) < 2:
        return False
    
    first_char = name_str[0]
    first_two_chars = name_str[:2] if len(name_str) >= 2 else first_char
    
    # 长度限制
    if first_char == '阿':
        if len(name_str) > 5:
            return False
    else:
        if len(name_str) > 4:
            return False
    
    # 非汉字字符检查
    if not all('\u4e00' <= c <= '\u9fff' for c in name_str):
        return False
    
    # 姓氏检查
    if first_char not in name.COMMON_SURNAMES and first_two_chars not in name.COMMON_SURNAMES:
        return False
    
    # 地区关键词结尾检查（按长关键词优先）
    if not skip_location_check and any(name_str.endswith(kw) for kw in LOCATION_KEYWORDS_SORTED):
        return False
    
    return True

def identify_special_fields(data):
    """逐行识别特殊字段（包含无姓名标签行的二次识别，保留已有特殊标签）"""
    if not data:
        return []
    rows_tags = []
    
    for row in data:
        row_tags = []
        name_candidates = []
        other_tags = []  # 存储身份证、手机、银行卡标签
        
        # 第一步：识别身份证、手机、银行卡，并收集姓名候选（首次过滤地区关键词）
        for idx, cell in enumerate(row):
            cell = cell.strip()
            tag = ''
            if validate_id_card(cell):
                tag = '身份证号'
            elif validate_phone(cell):
                tag = '手机号'
            elif validate_bank_card(cell):
                tag = '银行卡号'
            other_tags.append(tag)
            # 首次收集姓名候选（仅当该位置无特殊标签时）
            if tag == '' and validate_name(cell):
                name_candidates.append((idx, cell))
        
        # 处理首次识别出的姓名候选
        if name_candidates:
            # 处理三字和四字姓名优先级
            has_three_char = any(len(c[1]) == 3 for c in name_candidates)
            has_four_char = any(len(c[1]) == 4 for c in name_candidates)
            if has_three_char and has_four_char:
                three_char_candidates = [c for c in name_candidates if len(c[1]) == 3]
                selected_idx = three_char_candidates[0][0] if three_char_candidates else name_candidates[0][0]
            else:
                selected_idx = name_candidates[0][0]
            # 生成标签：保留已有特殊标签，新增姓名标签
            current_tags = other_tags.copy()
            current_tags[selected_idx] = '姓名'
            row_tags = current_tags
        else:
            # 第二步：对无姓名标签的行，重新识别（仅在无特殊标签的位置查找姓名）
            current_tags = other_tags.copy()  # 先保留已有特殊标签
            name_candidates_second = []
            for idx, cell in enumerate(row):
                cell = cell.strip()
                # 仅当该位置无特殊标签时，检查是否为姓名（二次识别时跳过地区关键词检查）
                if current_tags[idx] == '' and validate_name(cell, skip_location_check=True):
                    name_candidates_second.append((idx, cell))
            if name_candidates_second:
                # 二次识别处理逻辑
                has_three_char = any(len(c[1]) == 3 for c in name_candidates_second)
                has_four_char = any(len(c[1]) == 4 for c in name_candidates_second)
                if has_three_char and has_four_char:
                    three_char_candidates = [c for c in name_candidates_second if len(c[1]) == 3]
                    selected_idx = three_char_candidates[0][0] if three_char_candidates else name_candidates_second[0][0]
                else:
                    selected_idx = name_candidates_second[0][0]
                # 在空标签位置标记姓名
                if current_tags[selected_idx] == '':  # 双重验证，确保未被占用
                    current_tags[selected_idx] = '姓名'
            row_tags = current_tags
        
        rows_tags.append(row_tags)
    
    # 列重复率检查（保留原逻辑）
    column_names = defaultdict(list)
    for row_idx, row_tags in enumerate(rows_tags):
        for col_idx, tag in enumerate(row_tags):
            if tag == '姓名':
                column_names[col_idx].append(data[row_idx][col_idx])
    
    for col_idx, names in column_names.items():
        if not names:
            continue
        total = len(names)
        if total == 0:
            continue
        most_common = Counter(names).most_common(1)
        if (most_common and most_common[0][1] / total >= NAME_DUPLICATE_THRESHOLD) and total != 1:
            for row_idx in range(len(rows_tags)):
                if rows_tags[row_idx][col_idx] == '姓名':
                    rows_tags[row_idx][col_idx] = ''
    
    return rows_tags

def determine_title(data):
    """
    对比第一行与第二、三、四行（少数服从多数），判断是否为表头行
    - 若后续行不存在或为空，则跳过
    - 结果为1表示第一行是表头，0表示不是，None表示无法判断
    """
    if not data or len(data) < 1:
        log_message("错误：数据不足，至少需要1行")
        return None
    
    first_row = data[0]
    if not first_row or all(count_characters(cell) == 0 for cell in first_row):
        log_message("错误：第一行为空行")
        return None
    
    # 收集有效后续行（第二、三、四行，非空）
    valid_second_rows = []
    for row_idx in [1, 2, 3]:  # 对应第二、三、四行（索引1-3）
        if row_idx >= len(data):
            continue  # 行不存在，跳过
        current_row = data[row_idx]
        if not current_row or all(count_characters(cell) == 0 for cell in current_row):
            continue  # 空行，跳过
        valid_second_rows.append(current_row)
    
    if not valid_second_rows:
        log_message("警告：无有效后续行，无法判断表头")
        return None  # 无有效行，无法判断
    
    first_counts = [count_characters(cell) for cell in first_row]
    title_judgments = []
    
    for row in valid_second_rows:
        # 对齐列数，取最短列数（避免索引越界）
        min_cols = min(len(first_row), len(row))
        first_part = first_counts[:min_cols]
        row_part = [count_characters(cell) for cell in row[:min_cols]]
        
        # 计算第一行分量≥当前行分量的比例
        greater_or_equal = sum(1 for a, b in zip(first_part, row_part) if a >= b)
        ratio = greater_or_equal / min_cols if min_cols != 0 else 0
        
        # 判断是否为表头（原逻辑：ratio > 0.5 视为无表头（title=0），否则有表头（title=1））
        title_judge = 0 if ratio >= 0.5 else 1
        title_judgments.append(title_judge)
        log_message(f"对比第{row_idx+1}行：比例{ratio:.2f} → 判定title={title_judge}")
    
    # 少数服从多数统计
    counter = Counter(title_judgments)
    majority = counter.most_common(1)
    if len(majority) != 1 or counter[majority[0][0]] <= len(title_judgments) // 2:
        log_message(f"平局或无明显多数：判定结果{title_judgments}")
        return None  # 平局或无法确定
    else:
        final_title = majority[0][0]
        log_message(f"多数判定：{counter} → title={final_title}")
        return final_title

def log_message(message, to_console=True):
    """记录消息到日志文件，同时可选择输出到控制台"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(script_dir, PRIVATE_LOG)
        
        # 添加时间戳
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(full_message + "\n")
        
        if to_console:
            print(message)
    except Exception as e:
        # 如果日志记录失败，尝试输出到控制台
        if to_console:
            print(f"记录日志失败: {e}")
            print(message)

def load_processed_files(log_path):
    """加载已处理文件列表"""
    processed = set()
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    processed.add(line.strip())
            log_message(f"已加载 {len(processed)} 个已处理记录")
        except Exception as e:
            log_message(f"加载已处理文件列表失败: {e}")
    return processed

def save_processed_file(log_path, file_path):
    """保存已处理文件到日志"""
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{file_path}\n")
        log_message(f"已记录处理结果: {file_path}")
    except Exception as e:
        log_message(f"保存处理记录失败: {e}")

def get_unique_filename(target_dir, source_path):
    """生成唯一目标文件名（处理重名）"""
    filename = os.path.basename(source_path)
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        target_path = os.path.join(target_dir, filename)
        if not os.path.exists(target_path):
            return target_path
        filename = f"{base}_{counter}{ext}"
        counter += 1

def copy_to_unprocessed(source_path):
    """复制文件到未处理文件夹"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        unprocessed_dir = os.path.join(script_dir, UNPROCESSED_FOLDER)
        os.makedirs(unprocessed_dir, exist_ok=True)  # 创建目录（如果不存在）
        target_path = get_unique_filename(unprocessed_dir, source_path)
        shutil.copy2(source_path, target_path)
        log_message(f"已复制到未处理文件夹: {target_path}")
    except Exception as e:
        log_message(f"复制文件失败: {e}")

def create_table_if_not_exists():
    """创建private表（如果不存在），并确保包含所有字段"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()

            # 创建表（如果不存在）
            create_table_query = """
            CREATE TABLE IF NOT EXISTS private (
                id INT AUTO_INCREMENT PRIMARY KEY,
                身份证号 VARCHAR(18) NULL,
                手机号 VARCHAR(11) NULL,
                姓名 VARCHAR(255) NULL,
                银行卡号 VARCHAR(255) NULL,
                原始数据 JSON NULL,
                泄露渠道 VARCHAR(255) NULL,
                来源 VARCHAR(255) NULL,
                入库时间 DATETIME NULL
            )
            """
            cursor.execute(create_table_query)
            
            # 检查并添加缺失字段
            check_and_alter_column(cursor, '泄露渠道', 'VARCHAR(255) NULL')
            check_and_alter_column(cursor, '来源', 'VARCHAR(255) NULL')
            check_and_alter_column(cursor, '入库时间', 'DATETIME NULL')
            
            connection.commit()
            log_message("表结构已确保包含所有字段")
            return

        except Error as e:
            log_message(f"创建/修改表时出错 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                log_message("正在重试...")
            else:
                raise
        finally:
            if connection and connection.is_connected():
                cursor.close()
                connection.close()

def check_and_alter_column(cursor, column_name, column_def):
    """检查并添加缺失字段"""
    cursor.execute(f"SHOW COLUMNS FROM private LIKE '{column_name}'")
    if not cursor.fetchone():
        alter_table_query = f"ALTER TABLE private ADD COLUMN {column_name} {column_def}"
        cursor.execute(alter_table_query)
        log_message(f"已添加字段: {column_name}")

def insert_data_to_table(data, title, rows_tags, leak_channel, source, insert_time):
    """按行插入数据，使用行级tag"""
    max_retries = 3
    total_inserted = 0
    
    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()

            insert_query = """
            INSERT INTO private (
                身份证号, 手机号, 姓名, 银行卡号, 原始数据,
                泄露渠道, 来源, 入库时间
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            valid_data = []
            headers = data[0] if title == 1 and len(data) > 0 else []  # 获取表头行（title=1时）
            
            for i, row in enumerate(data):
                if title == 1 and i == 0:
                    continue  # 跳过表头行
                if i >= len(rows_tags):
                    continue  # 跳过tag不匹配的行
                
                raw_data = {}
                # 构建原始数据
                if title == 1:
                    for j, value in enumerate(row):
                        key = headers[j] if j < len(headers) else f"未知字段_{j}"
                        raw_data[key] = value
                else:
                    for j, value in enumerate(row):
                        raw_data[str(j)] = value
                
                # 按行tag提取字段
                id_card = None
                phone = None
                name = None
                bank_card = None
                row_tag = rows_tags[i]
                for j, value in enumerate(row):
                    if j >= len(row_tag):
                        continue
                    tag = row_tag[j]
                    if tag == '身份证号':
                        id_card = value
                    elif tag == '手机号':
                        phone = value
                    elif tag == '姓名':
                        name = value
                    elif tag == '银行卡号':
                        bank_card = value
                
                # 构建插入数据
                valid_data.append([
                    id_card,
                    phone,
                    name,
                    bank_card,
                    json.dumps(raw_data, ensure_ascii=False),
                    leak_channel,
                    source,
                    insert_time
                ])
            
            if valid_data:
                # 分批插入
                total_batches = (len(valid_data) + BATCH_SIZE - 1) // BATCH_SIZE
                for batch_num in range(total_batches):
                    start_idx = batch_num * BATCH_SIZE
                    end_idx = min(start_idx + BATCH_SIZE, len(valid_data))
                    batch = valid_data[start_idx:end_idx]
                    
                    cursor.executemany(insert_query, batch)
                    connection.commit()
                    total_inserted += len(batch)
                
                log_message(f"总共 {total_inserted} 条记录已插入")
            else:
                log_message("无有效数据可插入")
            return

        except Error as e:
            log_message(f"插入数据时出错 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                log_message("正在重试...")
                import time
                time.sleep(2 ** attempt)
            else:
                raise
        finally:
            if connection and connection.is_connected():
                cursor.close()
                connection.close()

# 新增：从文件名中提取支持的后缀
def get_correct_extension(filename, supported_extensions):
    """从文件名中提取支持的后缀（不区分大小写，优先长后缀）"""
    sorted_exts = sorted(supported_extensions, key=lambda x: -len(x))
    for ext in sorted_exts:
        if ext.lower() in filename.lower():
            return ext.lower()
    return None

def delete_records_by_source(source_path):
    """根据文件来源路径删除数据库记录"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            
            # 构建删除语句（使用来源字段精确匹配）
            delete_query = "DELETE FROM private WHERE 来源 = %s"
            script_dir = os.path.dirname(os.path.abspath(__file__))
            relative_path = os.path.relpath(source_path, script_dir)
            
            cursor.execute(delete_query, (relative_path,))

            connection.commit()
            print(cursor.rowcount)
            
            if cursor.rowcount > 0:
                log_message(f"成功删除 {cursor.rowcount} 条与 {source_path} 相关的记录")
            else:
                log_message(f"未找到与 {source_path} 相关的记录")
            
            return
            
        except Error as e:
            log_message(f"删除记录时出错 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                log_message("正在重试...")
                import time
                time.sleep(2 ** attempt)
            else:
                raise
        finally:
            if connection and connection.is_connected():
                cursor.close()
                connection.close()

def process_folder(folder_path, processed_files, log_path):
    """递归处理文件夹中的所有内容（增量处理）"""
    if not os.path.exists(folder_path):
        log_message(f"错误：文件夹 '{folder_path}' 不存在")
        return
    
    for item in os.listdir(folder_path):
        item_path = os.path.abspath(os.path.join(folder_path, item))
        
        if item_path in processed_files:
            log_message(f"跳过已处理项: {item_path}")
            continue
            
        if os.path.isdir(item_path):
            log_message(f"\n正在处理子文件夹: {item}")
            process_folder(item_path, processed_files, log_path)
        else:
            correct_ext = get_correct_extension(item, SUPPORTED_EXTENSIONS)
            if not correct_ext:
                log_message(f"忽略不支持的文件类型: {item}")
                continue
            
            log_message(f"\n正在处理文件（识别为{correct_ext}类型）: {item_path}")
            try:
                if correct_ext == 'txt':
                    data = process_txt_file(item_path)
                elif correct_ext == 'csv':
                    data = process_csv_file(item_path)
                elif correct_ext in ['xls', 'xlsx']:
                    data = process_excel_file(item_path)
                else:
                    raise ValueError(f"不支持的文件类型: {correct_ext}")
                
                if not data:
                    raise ValueError("文件内容为空")
                
                # 逐行识别字段
                rows_tags = identify_special_fields(data)
                
                # 统计未处理行比例（根据tag中非空字段数量）
                title = determine_title(data) if len(data)>=1 else None  # 至少需要1行数据
                data_rows = data[1:] if title == 1 and len(data)>1 else data
                tags_rows = rows_tags[1:] if title == 1 and len(rows_tags)>1 else rows_tags
                
                total_rows = len(data_rows)
                if total_rows == 0:
                    raise ValueError("无有效数据行")
                
                # 新的未处理行判定逻辑：tag中非空字段数量少于2
                unprocessed_rows = sum(1 for row_tags in tags_rows if sum(1 for tag in row_tags if tag) < 2)
                unprocess_ratio = unprocessed_rows / total_rows
                
                log_message(f"文件总行数: {total_rows}, 未处理行数: {unprocessed_rows}, 未处理比例: {unprocess_ratio:.2%}")
                
                if unprocess_ratio >= UNPROCESSED_THRESHOLD:  # 修改为大于等于80%
                    raise ValueError(f"未处理行比例达{unprocess_ratio*100:.1f}% >= {UNPROCESSED_THRESHOLD*100}%")
                
                # 获取新字段数据
                leak_channel = os.path.basename(item_path)
                script_dir = os.path.dirname(os.path.abspath(__file__))
                source = os.path.relpath(item_path, script_dir)
                insert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if title is not None:
                    insert_data_to_table(data, title, rows_tags, leak_channel, source, insert_time)
                
                save_processed_file(log_path, item_path)
                
            except Exception as e:
                log_message(f"处理文件失败: {e}，复制到未处理文件夹")
                copy_to_unprocessed(item_path)
                
                # 删除该文件对应的数据库记录
                delete_records_by_source(item_path)
                
                # 从已处理列表中移除（如果有）
                if item_path in processed_files:
                    processed_files.remove(item_path)
                    log_message(f"已从已处理列表中移除: {item_path}")

def process_txt_file(file_path):
    """按行读取txt文件，使用tokenize_text进行分词"""
    data = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line:
                    # 调用tokenize_text进行分词（仅保留连续汉字/数字）
                    tokens = tokenize_text(line)
                    if tokens:  # 过滤全空行
                        data.append(tokens)
    except Exception as e:
        # 尝试其他编码
        for enc in ['gbk', 'gb2312', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=enc, errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            tokens = tokenize_text(line)
                            if tokens:
                                data.append(tokens)
                return data
            except:
                continue
        raise

    return data

# 新增：CSV文件处理函数
def process_csv_file(file_path):
    """按行读取CSV文件并获取每列数据"""
    data = []
    try:
        df = pd.read_csv(file_path,low_memory=False)
        if df.empty:
            log_message("CSV表格为空")
            return data
        
        # 处理表头
        headers = [str(cell).strip() for cell in df.columns]
        if any(headers):  # 如果表头不全为空
            data.append(headers)
        
        # 处理数据行
        for _, row in df.iterrows():
            row_data = []
            for cell in row:
                cell_text = str(cell).strip() if pd.notna(cell) else ''
                row_data.append(cell_text)
            # 跳过全空行
            if any(row_data):
                data.append(row_data)
    except Exception as e:
        raise  # 抛出异常以便统一处理

    return data

def process_excel_file(file_path):
    """按行读取Excel文件并获取每列数据"""
    data = []
    try:
        engine = 'openpyxl' if file_path.endswith('.xlsx') else 'xlrd'
        df = pd.read_excel(file_path, engine=engine)
        if df.empty:
            log_message("表格为空")
            return data
        
        # 处理表头
        headers = [str(cell).strip() for cell in df.columns]
        if any(headers):  # 如果表头不全为空
            data.append(headers)
        
        # 处理数据行
        for _, row in df.iterrows():
            row_data = []
            for cell in row:
                # 将单元格内容转换为字符串，处理NaN值
                cell_text = str(cell).strip() if pd.notna(cell) else ''
                row_data.append(cell_text)
            # 跳过全空行
            if any(row_data):
                data.append(row_data)
    except Exception as e:
        raise  # 抛出异常以便统一处理
    return data

def tokenize_text(text):
    """
    终极文本分词处理
    - 非数字、汉字、字母的字符作为分隔符并删除
    - 汉字和数字相邻时，在中间插入分隔符并断开
    - 连续的数字、汉字、字母各自合并为一个token
    """
    if not text:
        return []
    
    # 第一步：将非数字、汉字、字母的字符替换为空格
    cleaned_text = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]', ' ', text)
    
    # 第二步：在汉字和数字之间插入空格（双向）
    # 处理 汉字→数字 的情况
    cleaned_text = re.sub(r'([\u4e00-\u9fff])([0-9])', r'\1 \2', cleaned_text)
    # 处理 数字→汉字 的情况
    cleaned_text = re.sub(r'([0-9])([\u4e00-\u9fff])', r'\1 \2', cleaned_text)
    
    # 第三步：分词并过滤空字符串
    return [token for token in cleaned_text.split() if token]

def count_characters(text):
    """统计字符数量（处理空字符串）"""
    if not text:
        return 0
    letters = sum(1 for c in text if c.isalpha() and not '\u4e00' <= c <= '\u9fff')
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    digits = sum(1 for c in text if c.isdigit())
    return letters + chinese + digits

def compare_first_two_elements(data):
    """比较前两行元素计算title值（处理空行）"""
    if len(data)<2 or not data[0] or not data[1]:
        log_message("错误：前两行数据不足或为空")
        return None
    
    first = data[0]
    second = data[1]
    first_counts = [count_characters(comp) for comp in first]
    second_counts = [count_characters(comp) for comp in second]
    
    x = len(first)
    y = sum(1 for i in range(min(x, len(second))) if first_counts[i] >= second_counts[i])
    ratio = y/x if x else 0
    title = 0 if ratio > 0.5 else 1
    
    log_message(f"\n比较结果: 第一个元素共有{x}个分量，其中{y}个分量大于或等于第二个元素的分量数量")
    log_message(f"比例: {ratio:.2f}")
    return title

def is_valid_date(year, month, day):
    """验证日期有效性（处理非法数字）"""
    try:
        if not (isinstance(year, int) and isinstance(month, int) and isinstance(day, int)):
            return False
        if not 1<=month<=12:
            return False
        days_in_month = [31,28,31,30,31,30,31,31,30,31,30,31]
        if (year%4==0 and year%100!=0) or year%400==0:
            days_in_month[1] = 29
        if not 1<=day<=days_in_month[month-1]:
            return False
        current_year = datetime.now().year
        if year < 1900 or year > current_year:
            return False
        return True
    except:
        return False

def validate_id_card(id_str):
    """完整身份证验证（包含校验码，加强空值和长度检查）"""
    if not id_str:
        return False
    id_str = id_str.upper().strip()
    if len(id_str) != 18:
        return False
    if not re.match(r'^\d{17}[0-9X]$', id_str):
        return False
    
    try:
        first_17 = list(map(int, id_str[:17]))
        checksum_char = id_str[17]
        total = sum(a * b for a, b in zip(first_17, ID_CARD_WEIGHTS))
        mod = total % 11
        expected_checksum = ID_CARD_CHECKSUM[mod]
        
        if checksum_char != expected_checksum:
            return False
        
        year = int(id_str[6:10])
        month = int(id_str[10:12])
        day = int(id_str[12:14])
        return is_valid_date(year, month, day)
    
    except:
        return False

def validate_bank_card(card_number):
    """验证银行卡号的有效性，包括长度和Luhn算法校验"""
    # 允许带空格的格式，先去除空格
    card_number = card_number.replace(' ', '')
    
    # 检查长度是否为16-19位
    if len(card_number) not in [16, 17, 18, 19]:
        return False
    
    # 检查是否全为数字
    if not card_number.isdigit():
        return False
    
    # Luhn算法校验
    digits = [int(d) for d in reversed(card_number)]
    checksum = 0
    
    for i, digit in enumerate(digits):
        if i % 2 == 1:
            doubled = digit * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += digit

    return checksum % 10 == 0


def main():
    """主函数：解析命令行参数并启动处理流程"""
    global FOLDER_TO_PROCESS
    
    parser = argparse.ArgumentParser(description='处理指定文件夹中的文本和Excel文件')
    parser.add_argument('-f', '--folder', help='要处理的文件夹路径', default=FOLDER_TO_PROCESS)
    args = parser.parse_args()
    FOLDER_TO_PROCESS = args.folder
    
    log_message(f"处理文件夹路径: {FOLDER_TO_PROCESS}")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, LOG_FILE)
    
    processed_files = load_processed_files(log_path)
    
    create_table_if_not_exists()
    
    log_message(f"\n开始处理文件夹: {FOLDER_TO_PROCESS}")
    process_folder(FOLDER_TO_PROCESS, processed_files, log_path)
    log_message("\n处理完成")

if __name__ == "__main__":
    main()
