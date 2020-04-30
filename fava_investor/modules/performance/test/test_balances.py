from beancount.utils import test_utils
from freezegun import freeze_time

from fava_investor.modules.performance.balances import get_balances_tree
from fava_investor.modules.performance.test.testutils import SplitTestCase, get_ledger

CONFIG = {"accounts_pattern": "^Assets:Account"}


class TestBalances(SplitTestCase):
    @test_utils.docfile
    @freeze_time("2020-03-10")
    def test_sums(self, filename: str):
        """
        2010-01-01 open Assets:Bank
        2010-01-01 open Assets:Account

        2020-01-01 * "transfer"
            Assets:Account  10 GBP
            Assets:Bank

        2020-03-01 * "transfer"
            Assets:Account  10 GBP
            Assets:Bank
        """
        tree = get_balances_tree(get_ledger(filename), CONFIG)
        self.assertEqual({("GBP", None): 20}, tree["Assets:Account"].balance)
        self.assertEqual({("GBP", None): 20}, tree["Assets"].balance_children)
        self.assertEqual({}, tree["Assets"].balance)

    @test_utils.docfile
    @freeze_time("2020-03-10")
    def test_it_has_value_accounts_and_ancestors(self, filename: str):
        """
        2010-01-01 open Assets:Bank
        2010-01-01 open Assets:Account

        2020-03-01 * "buy"
            Assets:Account  1 GBP
            Assets:Bank
        """

        tree = get_balances_tree(get_ledger(filename), CONFIG)
        self.assertTrue("Assets" in tree)
        self.assertTrue("Assets:Account" in tree)
        self.assertEqual(1, len(tree["Assets"].children))

        self.assertTrue("Assets:Bank" not in tree)
