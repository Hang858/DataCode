import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from .config import NAME_DUPLICATE_THRESHOLD
from . import name


BLACKLIST_NAMES = {
    "真名",
    "中国人",
    "用户名",
    "有限公司",
    "中国",
    "代收本金",
    "代收利息",
    "单元",
    "公积金",
    "先生",
    "女士",
    "小姐",
    "同志",
    "部门",
    "团队",
    "负责人",
    "联系人",
}

LOCATION_KEYWORDS = {"省", "市", "区", "县", "乡", "镇", "村", "街道", "地区", "自治州", "盟"}
LOCATION_KEYWORDS_SORTED = sorted(LOCATION_KEYWORDS, key=lambda x: -len(x))

ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECKSUM = {0: "1", 1: "0", 2: "X", 3: "9", 4: "8", 5: "7", 6: "6", 7: "5", 8: "4", 9: "3", 10: "2"}


@dataclass
class OfflineRecord:
    id_card: str | None
    phone: str | None
    person_name: str | None
    bank_card: str | None
    raw_data: str
    leak_channel: str
    source: str
    insert_time: str


def validate_phone(phone_str):
    phone_pattern = re.compile(r"^1[3-9]\d{9}$")
    return phone_pattern.match(str(phone_str).strip()) is not None


def validate_name(name_str, skip_location_check=False):
    if not name_str:
        return False
    name_str = str(name_str).strip()
    if name_str in BLACKLIST_NAMES:
        return False
    if len(name_str) < 2:
        return False

    first_char = name_str[0]
    first_two_chars = name_str[:2] if len(name_str) >= 2 else first_char

    if first_char == "阿":
        if len(name_str) > 5:
            return False
    elif len(name_str) > 4:
        return False

    if not all("\u4e00" <= c <= "\u9fff" for c in name_str):
        return False

    if first_char not in name.COMMON_SURNAMES and first_two_chars not in name.COMMON_SURNAMES:
        return False

    if not skip_location_check and any(name_str.endswith(kw) for kw in LOCATION_KEYWORDS_SORTED):
        return False

    return True


def validate_id_card(id_str):
    if not id_str:
        return False
    id_str = str(id_str).upper().strip()
    if len(id_str) != 18:
        return False
    if not re.match(r"^\d{17}[0-9X]$", id_str):
        return False

    try:
        first_17 = list(map(int, id_str[:17]))
        total = sum(a * b for a, b in zip(first_17, ID_CARD_WEIGHTS))
        if id_str[17] != ID_CARD_CHECKSUM[total % 11]:
            return False
        year = int(id_str[6:10])
        month = int(id_str[10:12])
        day = int(id_str[12:14])
        return is_valid_date(year, month, day)
    except Exception:
        return False


def validate_bank_card(card_number):
    if not card_number:
        return False
    card_number = str(card_number).replace(" ", "")
    if len(card_number) not in [16, 17, 18, 19]:
        return False
    if not card_number.isdigit():
        return False

    digits = [int(d) for d in reversed(card_number)]
    checksum = 0
    for i, digit in enumerate(digits):
        if i % 2 == 1:
            doubled = digit * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += digit
    return checksum % 10 == 0


def is_valid_date(year, month, day):
    try:
        if not (isinstance(year, int) and isinstance(month, int) and isinstance(day, int)):
            return False
        if not 1 <= month <= 12:
            return False
        days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0:
            days_in_month[1] = 29
        if not 1 <= day <= days_in_month[month - 1]:
            return False
        current_year = datetime.now().year
        return 1900 <= year <= current_year
    except Exception:
        return False


def tokenize_text(text):
    if not text:
        return []
    cleaned_text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", " ", str(text))
    cleaned_text = re.sub(r"([\u4e00-\u9fff])([0-9])", r"\1 \2", cleaned_text)
    cleaned_text = re.sub(r"([0-9])([\u4e00-\u9fff])", r"\1 \2", cleaned_text)
    return [token for token in cleaned_text.split() if token]


def count_characters(text):
    if not text:
        return 0
    text = str(text)
    letters = sum(1 for c in text if c.isalpha() and not "\u4e00" <= c <= "\u9fff")
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    digits = sum(1 for c in text if c.isdigit())
    return letters + chinese + digits


def identify_special_fields(data):
    if not data:
        return []
    rows_tags = []
    for row in data:
        name_candidates = []
        other_tags = []
        for idx, cell in enumerate(row):
            cell = str(cell).strip()
            tag = ""
            if validate_id_card(cell):
                tag = "身份证号"
            elif validate_phone(cell):
                tag = "手机号"
            elif validate_bank_card(cell):
                tag = "银行卡号"
            other_tags.append(tag)
            if tag == "" and validate_name(cell):
                name_candidates.append((idx, cell))

        current_tags = other_tags.copy()
        if not name_candidates:
            for idx, cell in enumerate(row):
                cell = str(cell).strip()
                if current_tags[idx] == "" and validate_name(cell, skip_location_check=True):
                    name_candidates.append((idx, cell))

        if name_candidates:
            has_three_char = any(len(c[1]) == 3 for c in name_candidates)
            has_four_char = any(len(c[1]) == 4 for c in name_candidates)
            if has_three_char and has_four_char:
                three_char_candidates = [c for c in name_candidates if len(c[1]) == 3]
                selected_idx = three_char_candidates[0][0] if three_char_candidates else name_candidates[0][0]
            else:
                selected_idx = name_candidates[0][0]
            if current_tags[selected_idx] == "":
                current_tags[selected_idx] = "姓名"
        if len(current_tags) < len(row):
            current_tags.extend([""] * (len(row) - len(current_tags)))
        rows_tags.append(current_tags)

    column_names = defaultdict(list)
    for row_idx, row_tags in enumerate(rows_tags):
        for col_idx, tag in enumerate(row_tags):
            if tag == "姓名" and col_idx < len(data[row_idx]):
                column_names[col_idx].append(data[row_idx][col_idx])

    for col_idx, names in column_names.items():
        if not names:
            continue
        most_common = Counter(names).most_common(1)
        if most_common and most_common[0][1] / len(names) >= NAME_DUPLICATE_THRESHOLD and len(names) != 1:
            for row_idx in range(len(rows_tags)):
                if col_idx < len(rows_tags[row_idx]) and rows_tags[row_idx][col_idx] == "姓名":
                    rows_tags[row_idx][col_idx] = ""

    return rows_tags


def determine_title(data, logger=None):
    if not data:
        return None

    first_row = data[0]
    if not first_row or all(count_characters(cell) == 0 for cell in first_row):
        if logger:
            logger("错误：第一行为空行")
        return None

    valid_second_rows = []
    for row_idx in [1, 2, 3]:
        if row_idx >= len(data):
            continue
        current_row = data[row_idx]
        if current_row and not all(count_characters(cell) == 0 for cell in current_row):
            valid_second_rows.append(current_row)

    if not valid_second_rows:
        if logger:
            logger("警告：无有效后续行，无法判断表头")
        return None

    first_counts = [count_characters(cell) for cell in first_row]
    title_judgments = []
    for row in valid_second_rows:
        min_cols = min(len(first_row), len(row))
        first_part = first_counts[:min_cols]
        row_part = [count_characters(cell) for cell in row[:min_cols]]
        greater_or_equal = sum(1 for a, b in zip(first_part, row_part) if a >= b)
        ratio = greater_or_equal / min_cols if min_cols else 0
        title_judgments.append(0 if ratio >= 0.5 else 1)

    counter = Counter(title_judgments)
    majority = counter.most_common(1)
    if len(majority) != 1 or counter[majority[0][0]] <= len(title_judgments) // 2:
        return None
    return majority[0][0]


def build_records(data, title, rows_tags, leak_channel, source, insert_time, headers=None, skip_header=None):
    headers = headers if headers is not None else (data[0] if title == 1 and data else [])
    skip_header = title == 1 if skip_header is None else skip_header
    for i, row in enumerate(data):
        if skip_header and i == 0:
            continue
        if i >= len(rows_tags):
            continue

        if headers:
            raw_data = {headers[j] if j < len(headers) else f"未知字段_{j}": value for j, value in enumerate(row)}
        else:
            raw_data = {str(j): value for j, value in enumerate(row)}

        id_card = None
        phone = None
        person_name = None
        bank_card = None
        row_tag = rows_tags[i]
        for j, value in enumerate(row):
            if j >= len(row_tag):
                continue
            tag = row_tag[j]
            if tag == "身份证号":
                id_card = value
            elif tag == "手机号":
                phone = value
            elif tag == "姓名":
                person_name = value
            elif tag == "银行卡号":
                bank_card = value

        yield OfflineRecord(
            id_card=id_card,
            phone=phone,
            person_name=person_name,
            bank_card=bank_card,
            raw_data=json.dumps(raw_data, ensure_ascii=False),
            leak_channel=leak_channel,
            source=source,
            insert_time=insert_time,
        )
