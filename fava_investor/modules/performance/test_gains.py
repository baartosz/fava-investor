from pprint import pformat

from beancount import loader
from beancount.core import convert, prices
from beancount.ops import validation
from beancount.utils import test_utils
from fava.core.tree import TreeNode

from beancountinvestorapi import AccAPI
from .contributions import get_accounts_from_config, Accounts
from .returns import returns

CONFIG = {"accounts_patterns": ["^Assets:Account"], "accounts_internal_patterns": []}


def get_beancount_ledger(filename):
    _, errors, _ = loader.load_file(
        filename, extra_validations=validation.HARDCORE_VALIDATIONS
    )
    if errors:
        raise ValueError("Errors in ledger file: \n" + pformat(errors))

    return AccAPI(filename, {})


class A:
    def __init__(self, accapi:AccAPI, accounts: Accounts):
        self.accapi = accapi
        self.accounts = accounts

    def get_unrealized_gains(self):
        tree = self.accapi.root_tree()

        price_map = prices.build_price_map(self.accapi.entries)
        node: TreeNode = tree.get("")
        return node.balance_children.reduce(convert.get_value, price_map)

    def get_realized_gains(self):
        pass

    def _get_selling_transactions(self):
        entries, _ = returns.internalize(
            self.accapi.entries, "Equity:Internalized", self.accounts.value, []
        )

        for entry in entries:
            if not returns.is_value_account_entry(
                    entry, self.accounts.value
            ) or not returns.is_external_flow_entry(
                entry, self.accounts.value | self.accounts.internal
            ):
                continue
            ext = []
            value = []
            for posting in entry.postings:
                if posting.account in self.accounts.value:
                    value.append(posting)
                else:
                    ext.append(posting)
            yield entry, value, ext


def get_sut(filename, config) -> A:
    accapi = get_beancount_ledger(filename)
    return A(accapi, get_accounts_from_config(accapi, config))


class TestGains(test_utils.TestCase):
    @test_utils.docfile
    def test_get_unrealized_gains(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account

        2020-02-22 * "Buy stock"
          Assets:Account  1 AA {1 USD}
          Assets:Bank

        2020-02-22 price AA  2 USD
        """
        sut = get_sut(filename, CONFIG)
        contributions = sut.get_unrealized_gains()

        self.assertEquals({"USD": 1}, contributions)

    @test_utils.docfile
    def test_ignoring_realized_gains(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account
        2020-01-01 open Income:Gains

        2020-02-22 * "realized gain"
          Assets:Account  1 AA {1 USD}
          Assets:Bank

        2020-02-23 * "realized gain"
          Assets:Account  -1 AA {1 USD}
          Assets:Bank  2 USD
          Income:Gains  -1 USD

        2020-02-24 * "unrealized gain"
          Assets:Account  1 AA {2 USD}
          Assets:Bank

        2020-02-24 price AA  4 USD
        """
        sut = get_sut(filename, CONFIG)
        result = sut.get_unrealized_gains()

        self.assertEquals({"USD": 2}, result)

    @test_utils.docfile
    def test_get_unrealized_gains(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account

        2020-02-22 * "Buy stock"
          Assets:Account  1 AA {1 USD}
          Assets:Bank

        2020-02-22 price AA  2 USD
        """
        sut = get_sut(filename, CONFIG)
        result = sut.get_unrealized_gains()

        self.assertEquals({"USD": 1}, result)

    @test_utils.docfile
    def test_realized_gains(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account
        2020-01-01 open Income:Gains

        2020-02-22 * "buy"
          Assets:Account  1 AA {1 USD}
          Assets:Bank

        2020-02-23 * "sell with gain"
          Assets:Account  -1 AA {1 USD}
          Assets:Bank  2 USD
          Income:Gains
        """
        sut = get_sut(filename, CONFIG)
        result = sut.get_realized_gains()

        self.assertEquals({"USD": 1}, result)
