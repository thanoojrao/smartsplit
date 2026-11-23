"""One tool per command (SPEC section 8): names, descriptions and input schemas.

The tools are not `strict`: strict structured output allows at most 20 strict tools and 16
union-typed parameters per request, and there are 29 commands. The schemas still guide the
model, and every call is decoded and checked; anything that doesn't decode is Unknown.
"""

from typing import get_args

from anthropic.types import ToolParam

from smartsplit.adapters.llm.tool_schemas import object_schema
from smartsplit.domain.commands import Command, Unknown

_NO_INPUT = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

COMMAND_CLASSES: tuple[type, ...] = get_args(Command.__value__)

DESCRIPTIONS: dict[str, str] = {
    "StartSplit": "Split the receipt photo just sent (or about to be). people: names said; "
    "everyone: 'everyone'; excluding: 'everyone except X'; payer: 'Sam paid'; owes_all: "
    "'Sam owes all of it'.",
    "AddManualBill": "Add a bill without a photo: 'rent 30000 with Sam and Raj'. amount in cents; "
    "exact: per-person cents when said ('Sam 12000, me 9000'); purchased_on: the date said, "
    "e.g. yesterday, as YYYY-MM-DD.",
    "AnswerPrompt": "An answer to one of the open questions: yes/no, a number from a list "
    "(choice), names of people, names excluded, or free text.",
    "Edit": "Change the bill under review (target null) or a saved bill ('last bill', a number "
    "from the last list, or its name). op is exactly one change; reason if they gave one.",
    "ConfirmDraft": "Save the bill under review ('looks good', 'save it', 'confirm').",
    "CancelDraft": "Drop the bill under review ('cancel', 'forget it').",
    "Acknowledge": "Just 'ok', 'thanks' or similar to a notification; nothing to do.",
    "FileIntoGroup": "Move the bill under review into a group: 'add to Flat 4B'.",
    "DeleteBill": "Delete a saved bill, with the reason if given.",
    "NotMine": "The speaker says a bill isn't theirs ('not mine').",
    "ShowBillDetails": "Show the full numbered list of a bill ('details', 'details 2').",
    "AddPerson": "Add someone by name and phone number ('add Priya 98765 43210'). In a group "
    "chat this adds a member.",
    "JoinGroup": "The speaker joins the group ('join', 'count me in').",
    "MemberLeft": "Someone left the group: 'Raj moved out' (person) or 'I moved out' (null).",
    "SetNickname": "What the speaker calls someone: 'call Samuel Sam'.",
    "CorrectNumber": "Fix the phone number given for someone: 'Priya's number is ...'.",
    "AddRule": "A preference about an item: exclude ('Raj doesn't drink milk'), soft_exclude "
    "('Sam usually skips chips'), only ('protein powder is Sam's'). subject null = speaker.",
    "DeleteRule": "Drop a preference: 'Raj drinks milk now'. subject null = speaker.",
    "ListRules": "List the preferences about someone ('rules about me': subject null).",
    "ShowBalances": "Who owes whom: overall, with one person, or in a named group.",
    "RecordPayment": "A payment between the speaker and one other person. Speaker paid: payer "
    "null, payee the other. Speaker received: payee null, payer the other. amount in cents; "
    "context_name if they said what it was for ('for the trip').",
    "NotReceived": "The speaker says a payment recorded to them never arrived.",
    "UndoPayment": "Undo the last payment the speaker recorded.",
    "SquareUp": "Clear every balance with one person into one: 'square up with Sam'.",
    "Remind": "Send someone a friendly reminder of what they owe: 'remind Raj'.",
    "ShowHistory": "Spending history: 'what did I spend this month' (period) or 'show last 5 "
    "bills' (last_n).",
    "Notifications": "'stop' (on false) or 'start' (on true) notifications and reminders.",
    "Help": "The speaker asks what the bot can do.",
    "Unknown": "Anything else, or not clearly meant for the bot.",
}


def command_tools() -> list[ToolParam]:
    """The tool list, in one fixed order so the prompt prefix stays cacheable."""
    return [_tool(cls) for cls in COMMAND_CLASSES]


def _tool(cls: type) -> ToolParam:
    return {
        "name": cls.__name__,
        "description": DESCRIPTIONS[cls.__name__],
        # Unknown always carries the original message, so the model fills in nothing.
        "input_schema": _NO_INPUT if cls is Unknown else object_schema(cls, tagged=False),
    }
