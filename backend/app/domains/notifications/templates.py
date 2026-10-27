"""Transactional email templates (plain text + HTML). HTML is autoescaped."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, StrictUndefined


@dataclass(frozen=True)
class Template:
    subject: str
    text: str
    html: str


_FOOTER_TEXT = "\n\n— AdVegaX\nIf you did not expect this email, you can ignore it."
_FOOTER_HTML = (
    "<p>— AdVegaX</p><p><small>If you did not expect this email, you can ignore it.</small></p>"
)

TEMPLATES: dict[str, Template] = {
    "email_verification": Template(
        subject="Verify your AdVegaX email address",
        text="Hello{{ ' ' ~ name if name }},\n\nConfirm your email address: {{ link }}\n"
        "This link expires in {{ expires_in }}." + _FOOTER_TEXT,
        html="<p>Hello{{ ' ' ~ name if name }},</p><p><a href=\"{{ link }}\">Confirm your email "
        "address</a>. This link expires in {{ expires_in }}.</p>" + _FOOTER_HTML,
    ),
    "account_exists": Template(
        subject="You already have an AdVegaX account",
        text="Someone tried to create an AdVegaX account with this email address, which already "
        "has an account.\nSign in: {{ sign_in_link }}\nForgot your password? "
        "{{ reset_link }}" + _FOOTER_TEXT,
        html="<p>Someone tried to create an AdVegaX account with this email address, which already "
        'has an account.</p><p><a href="{{ sign_in_link }}">Sign in</a> or '
        '<a href="{{ reset_link }}">reset your password</a>.</p>' + _FOOTER_HTML,
    ),
    "password_reset": Template(
        subject="Reset your AdVegaX password",
        text="Reset your password: {{ link }}\nThis link expires in {{ expires_in }}."
        + _FOOTER_TEXT,
        html='<p><a href="{{ link }}">Reset your password</a>. This link expires in '
        "{{ expires_in }}.</p>" + _FOOTER_HTML,
    ),
    "password_changed": Template(
        subject="Your AdVegaX password was changed",
        text="Your AdVegaX password was changed and other sessions were signed out. If this "
        "wasn't you, reset your password immediately: {{ reset_link }}" + _FOOTER_TEXT,
        html="<p>Your AdVegaX password was changed and other sessions were signed out.</p><p>If "
        'this wasn\'t you, <a href="{{ reset_link }}">reset your password</a> '
        "immediately.</p>" + _FOOTER_HTML,
    ),
    "invitation": Template(
        subject="You've been invited to {{ organization_name }} on AdVegaX",
        text="{{ inviter_name }} invited you to join {{ organization_name }} as {{ role }}.\n"
        "Accept the invitation: {{ link }}\nThis link expires in {{ expires_in }}." + _FOOTER_TEXT,
        html="<p>{{ inviter_name }} invited you to join "
        "<strong>{{ organization_name }}</strong> as "
        '{{ role }}.</p><p><a href="{{ link }}">Accept the invitation</a>. This link expires '
        "in {{ expires_in }}.</p>" + _FOOTER_HTML,
    ),
    "autopilot_changes": Template(
        subject="AdVegaX autopilot made changes for {{ organization_name }}",
        text="Autopilot made these changes for {{ organization_name }}, within the limits an "
        "owner set:\n{% for line in lines %}- {{ line }}\n{% endfor %}\nSee them, and undo any of "
        "them, under Changes: {{ link }}" + _FOOTER_TEXT,
        html="<p>Autopilot made these changes for <strong>{{ organization_name }}</strong>, "
        "within the limits an owner set:</p><ul>{% for line in lines %}<li>{{ line }}</li>"
        '{% endfor %}</ul><p><a href="{{ link }}">See them, and undo any of them, under '
        "Changes</a>.</p>" + _FOOTER_HTML,
    ),
    "autopilot_stopped": Template(
        subject="AdVegaX autopilot stopped for {{ organization_name }}",
        text="Autopilot stopped itself for {{ organization_name }}: {{ reason }}\nNothing more "
        "will change automatically until an owner switches it on again: {{ link }}" + _FOOTER_TEXT,
        html="<p>Autopilot stopped itself for <strong>{{ organization_name }}</strong>: "
        "{{ reason }}</p><p>Nothing more will change automatically until an owner "
        '<a href="{{ link }}">switches it on again</a>.</p>' + _FOOTER_HTML,
    ),
    "billing_trial_ending": Template(
        subject="Your AdVegaX trial for {{ organization_name }} ends on {{ ends }}",
        text="The free trial for {{ organization_name }} ends on {{ ends }}. Choose a plan to "
        "keep everything running; without one the organization becomes read-only (nothing is "
        "deleted): {{ link }}" + _FOOTER_TEXT,
        html="<p>The free trial for <strong>{{ organization_name }}</strong> ends on "
        '{{ ends }}.</p><p><a href="{{ link }}">Choose a plan</a> to keep everything running; '
        "without one the organization becomes read-only (nothing is deleted).</p>" + _FOOTER_HTML,
    ),
    "billing_payment_failed": Template(
        subject="AdVegaX payment failed for {{ organization_name }}",
        text="Stripe could not take the payment for {{ organization_name }}. Everything keeps "
        "working until {{ grace_ends }}; after that the organization becomes read-only until "
        "it is paid. Update the card: {{ link }}" + _FOOTER_TEXT,
        html="<p>Stripe could not take the payment for <strong>{{ organization_name }}"
        "</strong>.</p><p>Everything keeps working until {{ grace_ends }}; after that the "
        "organization becomes read-only until it is paid. "
        '<a href="{{ link }}">Update the card</a>.</p>' + _FOOTER_HTML,
    ),
    "billing_read_only": Template(
        subject="{{ organization_name }} is now read-only in AdVegaX",
        text="{{ organization_name }} is now read-only: everything stays visible, but nothing "
        "new is imported, changed or generated. Nothing has been deleted. Choose a plan or "
        "update the card to continue: {{ link }}" + _FOOTER_TEXT,
        html="<p><strong>{{ organization_name }}</strong> is now read-only: everything stays "
        "visible, but nothing new is imported, changed or generated. Nothing has been "
        'deleted.</p><p><a href="{{ link }}">Choose a plan or update the card</a> to '
        "continue.</p>" + _FOOTER_HTML,
    ),
    "billing_changed": Template(
        subject="AdVegaX billing changed for {{ organization_name }}",
        text="Billing for {{ organization_name }} changed: {{ summary }}.\nSee the details: "
        "{{ link }}" + _FOOTER_TEXT,
        html="<p>Billing for <strong>{{ organization_name }}</strong> changed: "
        '{{ summary }}.</p><p><a href="{{ link }}">See the details</a>.</p>' + _FOOTER_HTML,
    ),
    "security_notice": Template(
        subject="AdVegaX security notice",
        text="{{ message }}" + _FOOTER_TEXT,
        html="<p>{{ message }}</p>" + _FOOTER_HTML,
    ),
}

_text_env = Environment(autoescape=False, undefined=StrictUndefined)  # noqa: S701 (plain text)
_html_env = Environment(autoescape=True, undefined=StrictUndefined)


def render(name: str, variables: dict[str, Any]) -> tuple[str, str, str]:
    template = TEMPLATES[name]
    subject = _text_env.from_string(template.subject).render(**variables)
    text = _text_env.from_string(template.text).render(**variables)
    html = _html_env.from_string(template.html).render(**variables)
    return subject.replace("\n", " ").strip(), text, html
