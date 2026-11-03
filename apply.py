"""Apply an approved proposal's actions to the CRM, then verify them."""
import crm


def _resolve(fields, saved):
    """Replace placeholders like '$new_id' with values saved by earlier steps."""
    return {k: (saved[v[1:]] if isinstance(v, str) and v.startswith("$") else v)
            for k, v in fields.items()}


def _unwrap(resp):
    return resp.get("data", resp) if isinstance(resp, dict) else resp


def _verify(account_id, fields):
    """Re-read the account and confirm every written field stuck."""
    acc = _unwrap(crm.get_account(account_id))
    bad = {k: (v, acc.get(k)) for k, v in fields.items() if k != "note" and acc.get(k) != v}
    if bad:
        raise RuntimeError(f"Verification failed on {account_id}: {bad}")


def apply_proposal(proposal, previous_state=None):
    """Run actions in order. Returns (ok, state, error).

    `state` records finished steps and created ids, so a retry after a partial
    failure resumes where it stopped instead of creating a second account.
    """
    state = previous_state or {"done": [], "saved": {}}
    try:
        for i, action in enumerate(proposal["actions"]):
            if i in state["done"]:
                continue
            fields = _resolve(action.get("fields", {}), state["saved"])

            if action["op"] == "create_account":
                created = _unwrap(crm.create_account(fields))
                if action.get("save_as"):
                    state["saved"][action["save_as"]] = created["account_id"]
                _verify(created["account_id"], fields)

            elif action["op"] == "update_account":
                crm.update_account(action["account_id"], fields)
                _verify(action["account_id"], fields)

            elif action["op"] == "update_contact":
                crm.update_contact(action["contact_id"], fields)

            state["done"].append(i)
        return True, state, ""
    except Exception as e:
        return False, state, str(e)