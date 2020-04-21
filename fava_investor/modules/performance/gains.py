from beancount.core import prices, convert
from beancount.core.data import Transaction, Posting
from beancount.core.inventory import Inventory
from fava.core.inventory import CounterInventory
from fava.core.tree import TreeNode

from beancountinvestorapi import AccAPI
from .contributions import Accounts
from .returns import returns


class GainsCalculator:
    def __init__(self, accapi: AccAPI, accounts: Accounts):
        self.accapi = accapi
        self.accounts = accounts

    def get_unrealized_gains(self):
        tree = self.accapi.root_tree()

        price_map = prices.build_price_map(self.accapi.entries)

        result = CounterInventory()
        for acc in self.accounts.value:
            node: TreeNode = tree.get(acc)
            value = node.balance_children.reduce(convert.get_value, price_map)
            result.add_inventory(-node.balance_children.reduce(convert.get_cost))
            result.add_inventory(value)
        return result

    def get_realized_gains(self):
        rows = list(self._get_selling_transactions())
        return rows[len(rows) - 1][-1]

    def _get_selling_transactions(self):
        entries, _ = returns.internalize(
            self.accapi.entries, "Equity:Internalized", self.accounts.value, []
        )
        balance = Inventory()
        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            if not is_commodity_sale(entry, self.accounts.value):
                continue
            if not returns.is_internal_flow_entry(entry, self.accounts.internal):
                continue
            internal = Inventory()
            for posting in entry.postings:
                if posting.account in self.accounts.internal:
                    internal.add_position(posting)

            balance.add_inventory(-internal)
            yield entry, internal, balance


def is_commodity_sale(entry: Transaction, value_accounts):
    for posting in entry.postings:
        posting: Posting
        if posting.account not in value_accounts:
            continue
        if posting.units.number < 0 and posting.cost is not None:
            return True
    return False
