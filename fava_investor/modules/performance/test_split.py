import datetime
from pprint import pformat

from beancount import loader
from beancount.core import convert
from beancount.core.amount import Amount
from beancount.core.inventory import Inventory
from beancount.core.prices import get_price, get_latest_price
from beancount.ops import validation
from beancount.utils import test_utils
from fava.core import FavaLedger
from fava.util.date import Interval

from fava_investor import FavaInvestorAPI, get_balance_split_history
from fava_investor.modules.performance.split import (
    calculate_balances,
    sum_inventories,
    build_price_map_with_fallback_to_cost,
)


class SplitTestCase(test_utils.TestCase):
    def assertInventoriesSum(self, inventory_string, inventories: list):
        self.assertEqual(
            Inventory.from_string(inventory_string),
            sum_inventories(inventories),
            "Sum of given inventories does not match expected balance:\n"
            + pformat(inventories),
        )

    def assertInventory(self, expected_inventory_str, inventory):
        self.assertEqual(i(expected_inventory_str), inventory)

    def assertSumOfSplitsEqualValue(self, filename, account="Assets:Account"):
        ledger = get_ledger(filename)
        split = get_split(filename)
        final_value = get_value(
            ledger,
            build_price_map_with_fallback_to_cost(ledger.ledger.entries),
            account,
            ledger.ledger.entries[-1].date,
        )
        self.assertEqual(
            self.get_split_sum(split),
            final_value,
            f"Sum of splits doesnt equal {account} value. Splits: {self.get_readable_splits(split)}",
        )

    def assertSumOfSplitsEqual(self, filename, value):
        split = get_split(filename)
        self.assertEqual(
            self.get_split_sum(split),
            i(value),
            f"Sum of splits doesnt equal given inventory. Splits: {self.get_readable_splits(split)}",
        )

    def get_readable_splits(self, split):
        return (
                f"\ncontrib    {split.contributions}"
                + f"\nwithdrawal {split.withdrawals}"
                + f"\ndividends  {split.dividends}"
                + f"\ncosts      {split.costs}"
                + f"\ngains r.   {split.gains_realized}"
                + f"\ngains u.   {split.gains_unrealized}"
        )

    def get_split_sum(self, split):
        split_list = list(split)
        sum = sum_inventories([sum_inventories(s) for s in split_list])
        return sum


class TestSplit(SplitTestCase):
    @test_utils.docfile
    def test_no_dividends_counted_when_realizing_gain(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Income:Gains

        2020-01-05 * "realized gain"
            Assets:Account  1 SHARE {1 USD}
            Assets:Account

        2020-01-06 * "realized gain"
            Assets:Account  -1 SHARE {1 USD}
            Assets:Account
            Income:Gains  -1 USD
        """
        self.assertSumOfSplitsEqualValue(filename)

    @test_utils.docfile
    def test_splits_of_unrealized_gain(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank
        2020-01-01 open Expenses:ServiceFee
        2020-01-01 open Income:Dividends
        2020-01-01 open Income:Gains

        2020-01-02 * "unrealized gain"
            Assets:Account  1 SHARE {1 USD}
            Assets:Account

        2020-01-03 price SHARE 2 USD

        2020-01-04 * "irrelevant"
            Assets:Account  1 GBP
            Assets:Account
        """

        self.assertSumOfSplitsEqualValue(filename)

    @test_utils.docfile
    def test_unrealized_gains_in_discounted_purchase(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account
        2020-01-01 open Income:Gains

        2020-01-01 price AA 2 USD

        2020-01-02 * "buy discounted"
          Assets:Account  1 AA {1 USD}
          Assets:Account
        """
        self.assertSumOfSplitsEqualValue(filename)

    @test_utils.docfile
    def test_selling_with_commission(self, filename: str):
        """
        2020-01-01 open Assets:Bank
        2020-01-01 open Assets:Account
        2020-01-01 open Income:Gains
        2020-01-01 open Expenses:Commission

        2020-01-01 * "contrib and buy"
          Assets:Account       1 VLS {2 GBP}
          Assets:Bank         -2 GBP

        2020-01-01 * "sell with cost"
          Assets:Account      -1 VLS {2 GBP}
          Assets:Account       1 GBP
          Expenses:Commission  1 GBP

        """
        self.assertSumOfSplitsEqualValue(filename)

    @test_utils.docfile
    def test_sum_of_each_split_should_match_balance(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Expenses:ServiceFee
        2020-01-02 * "cost"
            Assets:Account  1 USD
            Expenses:ServiceFee
        """

        self.assertSumOfSplitsEqualValue(filename)


def get_value(ledger, price_map, account, date):
    if isinstance(date, str):
        date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    balance = ledger.root_tree()[account].balance
    reduce = balance.reduce(convert.get_value, price_map, date)
    inv = Inventory()
    for key, value in reduce.items():
        inv.add_amount(Amount(value, key))

    return inv


class TestPriceMap(SplitTestCase):
    def assertHasPrice(self, currency_pair, date_str, price_map):
        self.assertIn(
            currency_pair, price_map, msg=f"currency pair not found in given price map"
        )

        date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        prices_found = len(
            [
                amount
                for price_date, amount in price_map[currency_pair]
                if price_date == date
            ]
        )
        self.assertGreater(
            prices_found,
            0,
            msg=f"price not found for {currency_pair} and date {date_str}",
        )

    @test_utils.docfile
    def test_fallback_to_purchase_price(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank

        2020-01-01 * "contribution"
            Assets:Account  1 AA {1 USD}
            Assets:Bank
        """
        ledger = get_ledger(filename)
        entries = ledger.ledger.entries
        price_map = build_price_map_with_fallback_to_cost(entries)

        self.assertHasPrice(("AA", "USD"), "2020-01-01", price_map)

    @test_utils.docfile
    def test_no_fallback_if_there_is_earlier_price(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank

        2020-01-01 price AA 2 USD
        2020-01-02 * "contribution"
            Assets:Account  1 AA {1 USD}
            Assets:Bank
        """
        ledger = get_ledger(filename)
        price_map = build_price_map_with_fallback_to_cost(ledger.ledger.entries)

        self.assertEqual(
            i("2 USD"), get_value(ledger, price_map, "Assets:Account", "2020-01-02")
        )

    @test_utils.docfile
    def test_prices_from_purchases_after_first_one_are_not_used(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank

        2020-01-01 * "buy"
            Assets:Account  1 AA {1 USD}
            Assets:Bank

        2020-01-02 * "buy"
            Assets:Account  1 AA {2 USD}
            Assets:Bank
        """
        ledger = get_ledger(filename)
        price_map = build_price_map_with_fallback_to_cost(ledger.ledger.entries)

        self.assertEqual(1, get_latest_price(price_map, ("USD", "AA"))[1])

    @test_utils.docfile
    def test_no_fallback_if_there_is_price_in_following_entries_with_same_date(
            self, filename
    ):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank

        2020-01-02 * "contribution"
            Assets:Account  1 AA {1 USD}
            Assets:Bank

        2020-01-02 price AA 2 USD
        """
        ledger = get_ledger(filename)
        price_map = build_price_map_with_fallback_to_cost(ledger.ledger.entries)

        self.assertEqual(
            i("2 USD"), get_value(ledger, price_map, "Assets:Account", "2020-01-02")
        )


class TestIntervals(SplitTestCase):
    @test_utils.docfile
    def test_contributions_in_intervals(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank

        2020-01-02 * "contribution"
            Assets:Account  1 AA {1 USD}
            Assets:Bank

        2020-02-02 * "contribution"
            Assets:Account  1 AA {3 USD}
            Assets:Bank
        """
        split = get_split(filename, interval=Interval.MONTH)
        self.assertEqual(2, len(split.contributions))
        sum_week1 = sum_inventories([s[0] for s in split])
        self.assertInventory("1 USD", sum_week1)

        sum_week2 = sum_inventories([s[1] for s in split])
        self.assertInventory("3 USD", sum_week2)

    @test_utils.docfile
    def test_various_splits_in_intervals(self, filename):
        """
        2020-01-01 open Assets:Account
        2020-01-01 open Assets:Bank
        2020-01-01 open Income:Dividend
        2020-01-01 open Income:Gains

        2020-01-02 * "contribution"
            Assets:Account  1 AA {1 USD}
            Assets:Bank

        2020-02-02 * "dividend"
            Assets:Account
            Income:Dividend  -4 GBP

        2020-03-02 * "gain"
            Assets:Account  -1 AA {1 USD}
            Assets:Account
            Income:Gains  -5 USD
        """
        split = get_split_with_meta(filename, interval=Interval.MONTH)
        self.assertEqual(3, len(split.values))
        sum_week1 = sum_inventories([s[0] for s in split.parts])
        self.assertEqual(split.values[0], sum_week1)

        sum_week2 = sum_inventories([s[1] for s in split.parts])
        self.assertEqual(split.values[1], sum_week2)

        sum_week3 = sum_inventories([s[2] for s in split.parts])
        self.assertEqual(split.values[2], sum_week3)


class TestCalculateBalances(test_utils.TestCase):
    def test_calculating_balances(self):
        input = [i("10 GBP"), i("15 GBP")]
        balances = calculate_balances(input)

        expected = [i("10 GBP"), i("25 GBP")]
        self.assertEqual(expected, balances)

    def test_empty_list(self):
        balances = calculate_balances([])
        self.assertEqual([], balances)


def get_ledger(filename):
    _, errors, _ = loader.load_file(
        filename, extra_validations=validation.HARDCORE_VALIDATIONS
    )
    if errors:
        raise ValueError("Errors in ledger file: \n" + pformat(errors))

    return FavaInvestorAPI(FavaLedger(filename))


def get_split(filename, config_override=None, interval=None):
    split = get_split_with_meta(filename, config_override, interval=interval)
    return split.parts


def get_split_with_meta(filename, config_override=None, interval=None):
    defaults = {
        "accounts_pattern": "^Assets:Account",
        "accounts_income_pattern": "^Income:",
        "accounts_expenses_pattern": "^Expenses:",
        "accounts_internalized_pattern": "^Income:Dividends",
    }
    if not config_override:
        config_override = {}
    config = {**defaults, **config_override}
    ledger = get_ledger(filename)
    split = get_balance_split_history(
        ledger,
        config["accounts_pattern"],
        config["accounts_income_pattern"],
        config["accounts_expenses_pattern"],
        config["accounts_internalized_pattern"],
        interval=interval
    )
    return split


def i(string=""):
    return Inventory.from_string(string)
