import copy
from collections import namedtuple
from typing import List

from beancount.core import prices, convert
from beancount.core.data import Transaction, Posting
from beancount.core.inventory import Inventory
from fava.core import Tree
from fava.core.inventory import CounterInventory
from fava.core.tree import TreeNode

from .common import Accounts, filter_tree, get_accounts_from_config, get_accounts_with_parents
from .returns import returns


Row = namedtuple("Row", "transaction change balance")


class GainsCalculator:
    def __init__(self, accapi, accounts: Accounts):
        self.accapi = accapi
        self.accounts = accounts

    def get_unrealized_gains_per_account(self):
        tree = self.accapi.root_tree()

        price_map = prices.build_price_map(self.accapi.ledger.entries)

        result = {}
        for acc in self.accounts.value:
            node: TreeNode = tree.get(acc)
            value = node.balance.reduce(convert.get_value, price_map)
            a = CounterInventory()
            a.add_inventory(-node.balance.reduce(convert.get_cost))
            a.add_inventory(value)
            if a != {}:
                result[acc] = a
        return result

    def get_unrealized_gains_total(self):
        total = CounterInventory()
        per_account = self.get_unrealized_gains_per_account()
        for account, gain in per_account.items():
            total.add_inventory(gain)
        return total

    def get_realized_gains_total(self):
        rows = list(self.get_realized_gains_entries())
        return rows[len(rows) - 1][-1]

    def get_realized_gains_entries(self):
        entries, _ = returns.internalize(
            self.accapi.ledger.entries, "Equity:Internalized", self.accounts.value, []
        )
        balance = Inventory()
        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            if not self._is_commodity_sale(entry, self.accounts.value):
                continue
            if not returns.is_internal_flow_entry(entry, self.accounts.internal):
                continue
            internal = Inventory()
            for posting in entry.postings:
                if posting.account in self.accounts.internal:
                    internal.add_position(posting)

            balance.add_inventory(-internal)
            yield Row(entry, internal, balance)

    @staticmethod
    def _is_commodity_sale(entry: Transaction, value_accounts):
        for posting in entry.postings:
            posting: Posting
            if posting.account not in value_accounts:
                continue
            if posting.units.number < 0 and posting.cost is not None:
                return True
        return False


def get_balances_tree(accapi, config) -> Tree:
    accounts = get_accounts_from_config(accapi, config)
    tree = accapi.ledger.root_tree_closed
    filter_tree(tree, get_accounts_with_parents(accounts.value))
    return tree


class ContributionsCalculator:
    def __init__(self, accapi, accounts: Accounts):
        self.accapi = accapi
        self.accounts = accounts

    def get_contributions_total(self) -> Inventory:
        entries = self.get_contributions_entries()
        if not entries:
            return Inventory()
        return entries[len(entries) - 1].balance

    def get_contributions_entries(self) -> List[Row]:
        tx_tuples = self._get_external_x_value_postings()
        return self._filter_postings(
            tx_tuples, lambda posting: posting.units.number > 0
        )

    def get_withdrawals_total(self) -> Inventory:
        entries = self.get_withdrawals_entries()
        if not entries:
            return Inventory()
        return entries[len(entries) - 1].balance

    def get_withdrawals_entries(self) -> List[Row]:
        tx_tuples = self._get_external_x_value_postings()
        return self._filter_postings(
            tx_tuples, lambda posting: posting.units.number < 0
        )

    @staticmethod
    def _filter_postings(tx_tuples, match_lambda) -> List[Row]:
        result = []
        balance = Inventory()
        for entry, value, ext in tx_tuples:
            inventory = Inventory()
            for posting in value:
                if match_lambda(posting):
                    inventory.add_position(posting)
                    balance.add_inventory(inventory)

            if inventory != {}:
                result.append(Row(entry, inventory, copy.copy(balance)))
        return result

    def _get_external_x_value_postings(self):
        entries, _ = returns.internalize(
            self.accapi.ledger.entries, "Equity:Internalized", self.accounts.value, []
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


