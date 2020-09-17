import copy
from collections import namedtuple
from typing import List

from beancount.core.data import Transaction, Price
from beancount.core.inventory import Inventory
from beancount.core.prices import build_price_map
from fava.util.date import interval_ends

from fava_investor.modules.split.accumulators import UnrealizedGainAccumulator, CostAccumulator, \
    BalanceAccumulator, \
    RealizedGainAccumulator, DividendsAccumulator, ContributionAccumulator, Accounts, WithdrawalAccumulator

Split = namedtuple("Split", "transactions parts")
SplitParts = namedtuple(
    "SplitParts",
    "contributions withdrawals dividends costs gains_realized gains_unrealized balance errors",
)
Change = namedtuple("Change", "transaction change")


def calculate_split_parts(
        entries,
        accounts: Accounts,
        accumulators_ids: List[str],
        interval=None,
        begin=None,
        end=None
):
    # move that to u. gain accumulator, e.g. init()?
    add_dummy_transaction_if_has_entries_after_last_transaction(entries)

    next_interval_start = None
    if interval is not None and interval != 'transaction':
        dates = get_interval_end_dates(entries, interval)
        next_interval_start = dates.pop()

    accumulators = get_accumulators(accounts, entries, accumulators_ids)

    split_entries = SplitParts([], [], [], [], [], [], [], [])
    split = Split([], split_entries)

    first = True
    for entry in entries:
        if not isinstance(entry, Transaction):
            continue

        entry: Transaction
        if begin is not None and begin > entry.date:
            continue
        if end is not None and end <= entry.date:
            continue

        split.transactions.append(entry)

        if first is False and interval is not None and (interval == 'transaction' or entry.date > next_interval_start):
            if interval is not None and interval != 'transaction':
                next_interval_start = dates.pop()

            collect_results(accumulators, split_entries)

        for accum in accumulators:
            accum.process(entry)

        first = False

    collect_results(accumulators, split_entries)

    return split


def get_interval_end_dates(entries, interval):
    dates = list(interval_ends(entries[0].date, entries[-1].date, interval))
    if len(dates) == 1:
        dates.append(dates[0])
    dates = dates[1:]
    dates.reverse()
    return dates


def add_dummy_transaction_if_has_entries_after_last_transaction(entries):
    if has_prices_after_last_transaction(entries):
        date = copy.copy(entries[-1].date)
        entries.append(
            Transaction(
                None, date, None, None, "UNREALIZED GAINS NEW BALANCE", [], [], []
            )
        )


def get_accumulators(accounts: Accounts, entries, ids: List[str]):
    price_map = build_price_map(entries)
    accumulators = {
        'contributions': lambda: ContributionAccumulator(accounts),
        'withdrawals': lambda: WithdrawalAccumulator(accounts),
        'dividends': lambda: DividendsAccumulator(accounts),
        'gains_realized': lambda: RealizedGainAccumulator(accounts),
        'costs': lambda: CostAccumulator(accounts),
        'gains_unrealized': lambda: UnrealizedGainAccumulator(accounts, price_map),
        'balance': lambda: BalanceAccumulator(accounts, price_map),
    }

    return list([accumulators[key]() for key in ids])


def sum_inventories(inv_list):
    total = Inventory()
    for inv in inv_list:
        total += inv
    return total


def calculate_balances(inventories):
    if len(inventories) == 0:
        return []
    result = []
    balance = Inventory()
    for inv in inventories:
        balance += inv
        result.append(copy.copy(balance))
    return result


def has_prices_after_last_transaction(entries):
    has_prices_after_last_tx = False
    for entry in reversed(entries):
        if isinstance(entry, Price):
            has_prices_after_last_tx = True

        if isinstance(entry, Transaction):
            return has_prices_after_last_tx


def collect_results(accumulators, split_entries):
    for a in accumulators:
        getattr(split_entries, a.get_id()).append(a.get_result_and_reset())
