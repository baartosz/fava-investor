import re
from collections import namedtuple

from beancount.core.account import parents, parent
from fava.core.tree import TreeNode, Tree

Accounts = namedtuple("Accounts", "value internal external")


def filter_tree(tree, accounts_to_keep):
    for account in list(tree.keys()):
        if account not in accounts_to_keep:
            _remove_account_from_tree(tree, account)


def filter_matching(accounts, patterns):
    result = set()
    for account in accounts:
        if _is_value_account(account, patterns):
            result.add(account)
    return result


def get_accounts_from_config(accapi, config) -> Accounts:
    accounts = accapi.accounts
    value = filter_matching(
        accounts, config.get("accounts_patterns", [".*"])
    )
    internal = filter_matching(
        accounts, config.get("accounts_internal_patterns", [".*"])
    )
    external = set(accounts).difference(value | internal)
    return Accounts(value, internal, external)


def _remove_account_from_tree(tree: Tree, account: str):
    if account not in tree or account == "":
        return
    node = tree[account]
    for child in list(node.children):
        _remove_account_from_tree(tree, child.name)

    _remove_from_parent(account, node, tree)
    _reduce_parents_balances(account, node, tree)

    del tree[account]


def _reduce_parents_balances(account, node, tree):
    for parent_account in parents(account):
        parent_node: TreeNode = tree[parent_account]
        parent_node.balance_children.add_inventory(-node.balance)


def _remove_from_parent(account, node, tree):
    parent_account = parent(account)
    if parent_account is not None:
        parent_node: TreeNode = tree[parent_account]
        parent_node.children.remove(node)


def _is_value_account(account, patterns):
    for pattern in patterns:
        if re.match(pattern, account):
            return True
    return False


def get_accounts_with_parents(accounts):
    for value_acc in list(accounts):
        for p in parents(value_acc):
            accounts.add(p)
    return accounts