"""Fava Investor: Investing related reports and tools for Beancount/Fava"""
import copy

from beancount.core.inventory import Inventory
from fava.ext import FavaExtensionBase

from .modules import performance
from .modules.performance.balances import get_balances_tree
from .modules.performance.split import calculate_split_parts, sum_inventories, calculate_balances
from .modules.tlh import libtlh
from .modules.assetalloc_class import libassetalloc
from .modules.assetalloc_account import libaaacc
from .modules.cashdrag import libcashdrag
from .common.favainvestorapi import FavaInvestorAPI



class Investor(FavaExtensionBase):  # pragma: no cover
    report_title = "Split"

    # TaxLossHarvester
    # -----------------------------------------------------------------------------------------------------------
    def build_tlh_tables(self, begin=None, end=None):
        accapi = FavaInvestorAPI(self.ledger)
        return libtlh.get_tables(accapi, self.config.get('tlh', {}))

    def recently_sold_at_loss(self, begin=None, end=None):
        accapi = FavaInvestorAPI(self.ledger)
        return libtlh.recently_sold_at_loss(accapi, self.config.get('tlh', {}))

    # Performance
    # -----------------------------------------------------------------------------------------------------------
    def build_balances_tree(self):
        accapi = FavaInvestorAPI(self.ledger)
        return get_balances_tree(accapi, self.config.get('performance', {}))

    def _get_split(self, accumulators, for_journal=False):
        config = self.config.get("performance", {})
        split = calculate_split_parts(FavaInvestorAPI(self.ledger),
                                      accumulators,
                                      config.get("accounts_pattern", "^Assets:Investments"),
                                      config.get("accounts_income_pattern", "^Income:"),
                                      config.get("accounts_expenses_pattern", "^Expenses:"),
                                      interval='transaction' if for_journal else None,
                                      begin=self.ledger.filters.time.begin_date,
                                      end=self.ledger.filters.time.end_date,
                                      )
        return split

    def build_split_journal(self, kind):
        split = self._get_split([kind], True)
        split_values = getattr(split.parts, kind)
        to_keep = []
        for index in range(0, len(split.transactions)):
            if split_values[index] != {}:
                to_keep.append(index)
        balances = calculate_balances(split_values)

        return [(split.transactions[i], None, split_values[i], balances[i]) for i in range(0, len(split.transactions))
                if i in to_keep]

    def split_summary(self, begin=None, end=None):
        split = self._get_split(
            ['contributions', 'withdrawals', 'dividends', 'costs', 'gains_realized', 'gains_unrealized',
             'value_changes'])
        parts = split.parts
        summary = {'contributions': sum_inventories(parts.contributions),
                   'withdrawals': sum_inventories(parts.withdrawals),
                   'dividends': sum_inventories(parts.dividends),
                   'costs': sum_inventories(parts.costs),
                   'gains_realized': sum_inventories(parts.gains_realized),
                   'gains_unrealized': sum_inventories(parts.gains_unrealized),
                   }

        sum_of_splits = Inventory()
        for balance in summary.values():
            sum_of_splits += balance

        summary['value_changes'] = parts.value_changes[0]
        summary["sum_of_splits"] = sum_of_splits
        summary["error"] = sum_of_splits + -parts.value_changes[0]
        return summary
