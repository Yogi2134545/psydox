"""Psydox Billing UI — wallet balance, recharge packs, Razorpay checkout, transaction history."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as _components

from psydox.billing.models import RECHARGE_PACKS
from psydox.billing.service import get_billing_service


def _razorpay_checkout_html(
    key_id: str,
    order_id: str,
    amount_paise: int,
    pack_name: str,
    user_email: str,
) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;background:transparent;">
<div id="rz-status" style="font-family:sans-serif;padding:12px;text-align:center;color:#ccc;">
  Opening payment window…
</div>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
(function() {{
  var options = {{
    "key": "{key_id}",
    "amount": {amount_paise},
    "currency": "INR",
    "name": "Psydox AI Studio",
    "description": "Wallet Recharge — {pack_name}",
    "order_id": "{order_id}",
    "handler": function(response) {{
      document.getElementById('rz-status').innerText = 'Payment successful! Redirecting…';
      var origin = window.parent ? window.parent.location.origin : window.location.origin;
      var url = origin + "/?rzpay=1" +
                "&order_id=" + encodeURIComponent(response.razorpay_order_id) +
                "&payment_id=" + encodeURIComponent(response.razorpay_payment_id) +
                "&sig=" + encodeURIComponent(response.razorpay_signature);
      if (window.parent && window.parent !== window) {{
        window.parent.location.href = url;
      }} else {{
        window.location.href = url;
      }}
    }},
    "modal": {{
      "ondismiss": function() {{
        document.getElementById('rz-status').innerText = 'Payment cancelled. You can try again.';
      }}
    }},
    "prefill": {{ "email": "{user_email}" }},
    "theme": {{ "color": "#6366f1" }}
  }};
  var rzp = new Razorpay(options);
  rzp.on('payment.failed', function(resp) {{
    document.getElementById('rz-status').innerText =
      'Payment failed: ' + (resp.error.description || 'Unknown error');
  }});
  rzp.open();
}})();
</script>
</body>
</html>
"""


def render_wallet_page(on_back=None) -> None:
    """Full wallet / pricing page."""
    from psydox.billing import razorpay as _rz

    user_id    = st.session_state.get("user_id", "")
    user_email = st.session_state.get("user_email", "")
    user_role  = st.session_state.get("user_role", "viewer")
    bypass     = user_role in ("owner", "admin")

    billing = get_billing_service()

    # ── Header ─────────────────────────────────────────────────────────────────
    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown("## 💳 Wallet & Pricing")
    with bcol:
        if on_back and st.button("← Dashboard", use_container_width=True):
            on_back()

    # ── Success message from a payment return ──────────────────────────────────
    success_msg = st.session_state.pop("billing_success_msg", None)
    if success_msg:
        st.success(f"✅ {success_msg}")

    # ── Balance card ───────────────────────────────────────────────────────────
    if bypass:
        st.info("👑 Owner / Admin accounts have unlimited AI access — no wallet balance needed.")
    else:
        bal = billing.get_balance(user_id)
        b1, b2, b3 = st.columns(3)
        with b1:
            st.metric("Wallet Balance", f"₹{bal.balance_inr:.2f}")
        with b2:
            st.metric("Role", user_role.title())
        with b3:
            st.metric("AI Access", "Active" if bal.balance_paise > 0 else "Recharge needed")

    st.markdown("---")

    # ── Recharge packs ─────────────────────────────────────────────────────────
    st.markdown("### Recharge Packs")
    st.caption(
        "Pre-load your wallet. Every AI image generation deducts the actual API cost + a small markup.  \n"
        "Larger packs include **bonus credits** at no extra charge."
    )

    cols = st.columns(3)
    for i, pack in enumerate(RECHARGE_PACKS):
        col = cols[i % 3]
        with col:
            bonus_label = f"  •  **+{pack.bonus_pct}% bonus**" if pack.bonus_pct else ""
            credits_label = (
                f"₹{pack.credits_inr:.0f} in credits{bonus_label}"
                if pack.bonus_pct else
                f"₹{pack.amount_inr} in credits"
            )
            st.markdown(
                f"""
<div style="border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:14px;
     margin-bottom:12px;background:rgba(255,255,255,.03);">
  <div style="font-weight:700;font-size:1rem;color:#e2e8f0;">{pack.name}</div>
  <div style="font-size:1.6rem;font-weight:800;color:#6366f1;margin:4px 0;">₹{pack.amount_inr}</div>
  <div style="font-size:0.78rem;color:#94a3b8;">{credits_label}</div>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button(
                f"Recharge ₹{pack.amount_inr}",
                key=f"buy_{pack.id}",
                use_container_width=True,
                type="primary",
                disabled=bypass,
            ):
                if not _rz.is_configured():
                    st.error(
                        "Payment gateway not configured. "
                        "Ask the admin to set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."
                    )
                else:
                    try:
                        order_info = billing.create_topup_order(user_id, pack.id)
                        st.session_state["billing_checkout"] = {
                            "order_id":     order_info["order_id"],
                            "amount_paise": order_info["amount_paise"],
                            "credits_paise": order_info["credits_paise"],
                            "pack_name":    order_info["pack_name"],
                            "key_id":       order_info["key_id"],
                        }
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not create payment order: {e}")

    # ── Razorpay checkout component (shown after user picks a pack) ────────────
    checkout = st.session_state.get("billing_checkout")
    if checkout:
        st.markdown("---")
        st.markdown("#### Complete Your Payment")
        st.caption(
            f"Recharging **₹{checkout['amount_paise'] // 100}** → "
            f"**₹{checkout['credits_paise'] // 100}** in wallet credits"
        )
        if st.button("❌ Cancel", key="billing_cancel_checkout"):
            st.session_state.pop("billing_checkout", None)
            st.rerun()
        else:
            html = _razorpay_checkout_html(
                key_id=checkout["key_id"],
                order_id=checkout["order_id"],
                amount_paise=checkout["amount_paise"],
                pack_name=checkout["pack_name"],
                user_email=user_email,
            )
            _components.html(html, height=120, scrolling=False)

    st.markdown("---")

    # ── Pricing explainer ──────────────────────────────────────────────────────
    with st.expander("💡 How pricing works", expanded=False):
        st.markdown(
            """
**Pay-per-use model**

Each AI image generation deducts from your wallet based on the actual API provider cost,
plus a small platform markup.

| Tool | Approx. cost per image |
|---|---|
| AI Background | ₹0.60 |
| AI Lifestyle | ₹1.20 |
| AI Model Shot | ₹1.80 |
| AI Scene | ₹1.20 |
| AI Angles (per angle) | ₹0.60 |
| Jadu Ka Ghar | ₹1.20 |

Classic tools (Resize, Crop, Enhance, Masking, etc.) are **always free**.

Wallet balance never expires.
"""
        )

    # ── Transaction history ────────────────────────────────────────────────────
    if not bypass:
        st.markdown("### Recent Transactions")
        txns = billing.get_transactions(user_id, limit=20)
        if not txns:
            st.caption("No transactions yet.")
        else:
            for txn in txns:
                import datetime
                dt = datetime.datetime.fromtimestamp(txn.created_at).strftime("%Y-%m-%d %H:%M")
                sign = "+" if txn.type == "credit" else "−"
                color = "#22c55e" if txn.type == "credit" else "#f87171"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:6px 0;'
                    f'border-bottom:1px solid rgba(255,255,255,.05);font-size:0.85rem;">'
                    f'<span style="color:#cbd5e1;">{txn.description[:60]}</span>'
                    f'<span style="color:{color};font-weight:600;">'
                    f'{sign}₹{txn.amount_inr:.2f}</span>'
                    f'<span style="color:#64748b;font-size:0.75rem;">{dt}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
