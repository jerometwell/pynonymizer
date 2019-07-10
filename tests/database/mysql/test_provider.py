import unittest
import pytest
import os
from subprocess import CalledProcessError
from unittest.mock import Mock, patch, MagicMock, call, mock_open
from pynonymizer.database.mysql import MySqlProvider
from pynonymizer.strategy.database import DatabaseStrategy
from pynonymizer.strategy.table import TruncateTableStrategy, UpdateColumnsTableStrategy
from pynonymizer.strategy.update_column import UniqueEmailUpdateColumnStrategy, UniqueLoginUpdateColumnStrategy, FakeUpdateColumnStrategy, EmptyUpdateColumnStrategy
from pynonymizer.database.exceptions import UnsupportedTableStrategyError


@patch("pynonymizer.database.mysql.execution", autospec=True)
def test_init_runners_correctly(execution):
    """
    Test the provider inits dependencies with the correct database information
    """
    MySqlProvider("1.2.3.4", "root", "password", "db_name")
    execution.MySqlCmdRunner.assert_called_once_with("1.2.3.4", "root", "password", "db_name")
    execution.MySqlDumpRunner.assert_called_once_with("1.2.3.4", "root", "password", "db_name")


@patch("pynonymizer.database.mysql.execution", autospec=True)
@patch("pynonymizer.database.mysql.query_factory", autospec=True)
class DatabaseQueryExecTests(unittest.TestCase):
    def test_create_database(self, query_factory, execution):
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        provider.create_database()

        # assert that the query factory is called with the db name, and the output is passed to the execute runner
        query_factory.get_create_database.assert_called_once_with("db_name")
        execution.MySqlCmdRunner.return_value.execute.assert_called_once_with(query_factory.get_create_database.return_value)

    def test_drop_database(self, query_factory, execution):
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        provider.drop_database()

        # assert that the query factory is called with the db name, and the output is passed to the execute runner
        query_factory.get_drop_database.assert_called_once_with("db_name")
        execution.MySqlCmdRunner.return_value.execute.assert_called_once_with(query_factory.get_drop_database.return_value)

    def test_connection(self, query_factory, execution):
        # test_connection should return the cmd runner's test output (bool)
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        assert provider.test_connection() == execution.MySqlCmdRunner.return_value.test.return_value

    @patch("pynonymizer.database.mysql.resolve_input")
    def test_restore_database(self, resolve_input, query_factory, execution):
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        rand_data = bytes( os.urandom(8193) )
        mock_input = Mock(get_size=Mock(return_value=8193), open=mock_open(read_data=rand_data))
        resolve_input.return_value = mock_input

        provider.restore_database("testfile.bbs")

        # ask for size
        mock_input.get_size.assert_called()
        # open input and read at least once
        mock_input.open.assert_called()
        mock_input.open.return_value.read.assert_called()
        # open, write and flush at least once
        execution.MySqlCmdRunner.return_value.open_batch_processor.assert_called_once_with()
        execution.MySqlCmdRunner.return_value.open_batch_processor.return_value.write.assert_called()
        execution.MySqlCmdRunner.return_value.open_batch_processor.return_value.flush.assert_called()

    @patch("pynonymizer.database.mysql.resolve_output")
    def test_dump_database(self, resolve_output, query_factory, execution):
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        rand_data = bytes( os.urandom(8192) )
        mock_output = Mock(open=mock_open())
        resolve_output.return_value = mock_output

        execution.MySqlDumpRunner.return_value.open_dumper.return_value = MagicMock(read=MagicMock(side_effect=[rand_data, b""]))

        provider.dump_database("testfile.bbs")

        # open output and write at least once
        mock_output.open.assert_called()
        mock_output.open.return_value.write.assert_called()

        # open dumper and read at least once
        execution.MySqlDumpRunner.return_value.open_dumper.assert_called_once_with()
        execution.MySqlDumpRunner.return_value.open_dumper.return_value.read.assert_called()

    def test_anonymize_database_unsupported_table_strategy(self, query_factory, execution):
        with pytest.raises(UnsupportedTableStrategyError) as e_info:
            provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
            database_strategy = DatabaseStrategy([
                    Mock(table_name="table1", strategy_type="DEFINITELY_NOT_A_SUPPORTED_STRATEGY_TYPE"),
            ])
            provider.anonymize_database(database_strategy)


    def test_anonymize_database(self, query_factory, execution):
        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        database_strategy = DatabaseStrategy([
                TruncateTableStrategy("table1"),
                UpdateColumnsTableStrategy("table2", [
                    UniqueEmailUpdateColumnStrategy("column1"),
                    UniqueLoginUpdateColumnStrategy("column2"),
                    FakeUpdateColumnStrategy("column3", Mock(), "user_name"),
                    EmptyUpdateColumnStrategy("column4")
                ])
            ])

        provider.anonymize_database(database_strategy)

        # Assert that queries are executed that roughly match the process.
        execution.MySqlCmdRunner.return_value.db_execute.assert_any_call(query_factory.get_create_seed_table.return_value)
        execution.MySqlCmdRunner.return_value.db_execute.assert_any_call(query_factory.get_insert_seed_row.return_value)
        execution.MySqlCmdRunner.return_value.db_execute.assert_any_call(query_factory.get_truncate_table.return_value)
        execution.MySqlCmdRunner.return_value.db_execute.assert_any_call(query_factory.get_update_table.return_value)
        execution.MySqlCmdRunner.return_value.db_execute.assert_any_call(query_factory.get_drop_seed_table.return_value)

    def test_before_script_run(self,query_factory, execution):
        manager = Mock()
        manager.attach_mock(execution, "execution")

        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        database_strategy = DatabaseStrategy(table_strategies=[
                TruncateTableStrategy("table1")
            ],
            before_scripts=["SELECT `before` FROM `before_table`;"]
        )

        provider.anonymize_database(database_strategy)

        truncate_call_index = manager.mock_calls.index(call.execution.MySqlCmdRunner().db_execute(query_factory.get_truncate_table.return_value))
        before_script_call_index = manager.mock_calls.index( call.execution.MySqlCmdRunner().db_execute("SELECT `before` FROM `before_table`;") )

        # before script should be before any anonymization happens (truncate)
        assert before_script_call_index < truncate_call_index

    def test_after_script_run(self,query_factory,execution):
        manager = Mock()
        manager.attach_mock(execution, "execution")

        provider = MySqlProvider("1.2.3.4", "root", "password", "db_name")
        database_strategy = DatabaseStrategy(table_strategies=[
                TruncateTableStrategy("table1")
            ],
            after_scripts=["SELECT `after` FROM `after_table`;"]
        )
        provider.anonymize_database(database_strategy)

        truncate_call_index = manager.mock_calls.index(call.execution.MySqlCmdRunner().db_execute(query_factory.get_truncate_table.return_value))
        after_script_call_index =  manager.mock_calls.index( call.execution.MySqlCmdRunner().db_execute("SELECT `after` FROM `after_table`;") )

        # after script should be called after anonymization
        assert truncate_call_index < after_script_call_index

