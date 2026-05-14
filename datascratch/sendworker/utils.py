def to_datetime_string(value):
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value.strftime("%Y-%m-%d")
    return value


def extract_file_ids(item):
    file_ids = []
    if item.get("child_file"):
        if isinstance(item["child_file"], str):
            file_ids = [fid.strip() for fid in item["child_file"].split(",") if fid.strip()]
        elif isinstance(item["child_file"], list):
            file_ids = item["child_file"]
    return file_ids
