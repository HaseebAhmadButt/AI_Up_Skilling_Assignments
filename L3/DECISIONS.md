# L2 decisions and known limits

## Guards added
- Routing: `COMPLETE` is accepted only when every approver in the chain is APPROVED; `ASSIGN_NEXT` only for the next approver, who must still be pending. Missing, ambiguous (several different `ACTION` lines) or unparseable output is logged, retried up to 3 times with the request left pending, then escalated for manual action. Trailing spaces and case are tolerated.
- Identity: `submit_request` refuses a request whose email is not the email on record for the requester ID (REQ-0001 case: E2001 Ali Raza with haseeb.ahmad@example.com). Nothing is guessed.
- Manager label: the policy role is `Manager`; the directory title ("Manager Marketing Department") is only the person's job title. Portals and routing messages both label stage 1 as `Manager`.

## Decisions
- Substitute route: `SUBSTITUTE_APPROVERS` in `mock_data/employees.py` (E2001 -> Zain Abbas E5001) is the configured authority, set by whoever maintains that mapping, not confirmed per request. If there is no substitute, or the substitute is the requester, validation fails and no workflow is created. There is no availability model: an unavailable substitute stays silent, gets reminders, then the request escalates for manual action.
- Resubmission after rejection (F8): ALLOWED. The duplicate rule (same email + software) blocks only while the earlier request is pending, approved, blocked or escalated; a rejected request is terminal and stays untouched. Tested.
- Rejection reason (E5): a stripped reason of at least 10 characters (spaces count) and at least 2 words. Newlines and repeated whitespace are collapsed to single spaces before storing, so history and logs stay single-line. No length cap.
- Typed Manager name: only a check against the manager of record (or the stage approver), enforced by the tool and again by `validate_agent_result`. It never selects an approver, so the two "Ali Raza" employees (E2001, E2003) cannot be confused.
- Substitute decisions: history names the substitute and the requester who is the manager of record.
- Silence and timeouts: reminders and escalation never record a decision. Escalation sets status `escalated` with all decisions unset and blocks further decisions (covered by a test).

## Known limits
- The scheduler thread prints to the same console as the menus, so output can interleave with prompts (for example stray "Invalid selection" lines). Cosmetic; use `L2/logs` for evidence.
