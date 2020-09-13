"""Fava Investor: Investing related reports and tools for Beancount/Fava"""
import copy
import re

from beancount.core.inventory import Inventory
from fava.ext import FavaExtensionBase

from .modules import split
from .modules.split.accumulators import Accounts
from .modules.split.balances import get_balances_tree
from .modules.split.split import calculate_split_parts, sum_inventories, calculate_balances
from .modules.tlh import libtlh
from .modules.assetalloc_class import libassetalloc
from .modules.assetalloc_account import libaaacc
from .modules.cashdrag import libcashdrag
from .common.favainvestorapi import FavaInvestorAPI


def extract_accounts(accounts, expenses_pattern, income_pattern, pattern_value):
    accounts_value = set([acc for acc in accounts if re.match(pattern_value, acc)])
    accounts_expenses = set(
        [acc for acc in accounts if re.match(expenses_pattern, acc)]
    )
    accounts_income = set([acc for acc in accounts if re.match(income_pattern, acc)])
    accounts = Accounts(accounts_value, accounts_income, accounts_expenses)
    return accounts


def split_with_fava_config(ledger, accumulators, for_journal, ledger_accounts):
    split = calculate_split_parts(ledger.entries,
                                  ledger_accounts,
                                  accumulators,
                                  interval='transaction' if for_journal else None,
                                  begin=ledger.filters.time.begin_date,
                                  end=ledger.filters.time.end_date,
                                  )
    return split


def get_accounts(config, ledger_accounts):
    accounts = extract_accounts(ledger_accounts,
                                config.get("accounts_expenses_pattern", "^Expenses:"),
                                config.get("accounts_income_pattern", "^Income:"),
                                config.get("accounts_pattern", "^Assets:Investments")
                                )
    return accounts


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

    def _get_split(self, portfolio, accumulators, for_journal=False):
        accounts = self._get_accounts_from_self(portfolio)
        split = split_with_fava_config(self.ledger, accumulators, for_journal, accounts)
        return split

    def _get_accounts_from_self(self, portfolio):
        config = self.config.get("split", {})
        value_pattern = [p[1] for p in config["portfolios"] if p[0] == portfolio][0]
        accounts = extract_accounts(self.ledger.accounts,
                                    config.get("accounts_expenses_pattern", "^Expenses:"),
                                    config.get("accounts_income_pattern", "^Income:"),
                                    value_pattern
                                    )
        return accounts

    def build_split_journal(self, kind, portfolio):
        split = self._get_split(portfolio, [kind], True)
        split_values = getattr(split.parts, kind)
        to_keep = []
        for index in range(0, len(split.transactions)):
            if split_values[index] != {}:
                to_keep.append(index)
        balances = calculate_balances(split_values)

        return [(split.transactions[i], None, split_values[i], balances[i]) for i in range(0, len(split.transactions))
                if i in to_keep]

    def get_portfolios(self):
        ports = self.config.get("split")["portfolios"]
        return [p[0] for p in ports]

    def split_summary(self, portfolio):
        split = self._get_split(portfolio,
            ['contributions', 'withdrawals', 'dividends', 'costs', 'gains_realized', 'gains_unrealized',
             'balance'])
        parts = split.parts
        summary = {'contributions': sum_inventories(parts.contributions),
                   'withdrawals': sum_inventories(parts.withdrawals),
                   '(net_contrib.)': sum_inventories(parts.contributions + parts.withdrawals),
                   'dividends': sum_inventories(parts.dividends),
                   'costs': sum_inventories(parts.costs),
                   '(net_div.)': sum_inventories(parts.dividends+ parts.costs),
                   'gains_realized': sum_inventories(parts.gains_realized),
                   'gains_unrealized': sum_inventories(parts.gains_unrealized),
                   '(net_gains)': sum_inventories(parts.gains_realized+ parts.gains_unrealized),
                   }

        sum_of_splits = Inventory()
        for key, balance in summary.items():
            if '(' not in key:
                sum_of_splits += balance

        summary['balance'] = parts.balance[0]
        summary["sum_of_splits"] = sum_of_splits
        summary["error"] = sum_of_splits + -parts.balance[0]
        return summary

    def accounts(self, portfolio):
        acc = self._get_accounts_from_self(portfolio)
        output = {}
        output["value"] = acc.value
        output["expense"] = acc.expenses
        output["income"] = acc.income
        return output
