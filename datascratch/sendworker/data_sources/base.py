class BaseDataSource:
    def get_connection(self):
        raise NotImplementedError

    def fetch_submission_flags(self, cursor, task_id):
        raise NotImplementedError

    def fetch_task_filters(self, cursor, task_id, dataset):
        raise NotImplementedError

    def resolve_telegram_time_range(self, cursor, task_id, module, start_date, end_date):
        raise NotImplementedError

    def resolve_darknet_time_range(self, cursor, task_id, module, start_date, end_date):
        raise NotImplementedError

    def fetch_telegram_rows(self, connection, start_date, end_date):
        raise NotImplementedError

    def fetch_darknet_rows(self, connection, start_date, end_date):
        raise NotImplementedError

    def fetch_scheduler_configs(self, cursor, task_id=None):
        raise NotImplementedError
