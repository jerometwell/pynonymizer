class DatabaseConnectionError(Exception):
    def __init__(self):
        super().__init__("Unable to connect to database. check your settings.")


class MissingPrerequisiteError(Exception):
    def __init__(self, message):
        super().__init__(message)


class UnsupportedTableStrategyError(Exception):
    def __init__(self, table_strategy):
        super().__init__("Unsupported Table Strategy: {}".format(table_strategy))

class UnknownDatabaseTypeError(Exception):
    def __init__(self, database_type):
        self.database_type = database_type
        super().__init__("Unknown Database Type: {}".format(database_type))
