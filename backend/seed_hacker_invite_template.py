"""Add the hacker-themed invitation email template."""
import asyncio
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models.email_template import EmailTemplate


HACKER_INVITE_TEMPLATE = {
    "name": "invite",  # Replace existing invite template
    "display_name": "Hacker-Themed Invitation",
    "description": "Cyberpunk-styled invitation email for CyberX events",
    "subject": "ACCESS GRANTED: {event_name} Invitation",
    "html_content": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="X-UA-Compatible" content="IE=edge" />
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
<meta name="x-apple-disable-message-reformatting" />
<title>You're In.</title>
<!--[if mso]>
<style type="text/css">
  body, table, td { font-family: Arial, sans-serif !important; }
</style>
<![endif]-->
<style>
  /* ─── Google Fonts ─── */
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&display=swap');

  /* ─── Reset ─── */
  * { margin: 0; padding: 0; box-sizing: border-box; }

  /* Email client resets */
  body {
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
    -webkit-text-size-adjust: 100%;
    -ms-text-size-adjust: 100%;
  }

  img {
    border: 0;
    height: auto;
    line-height: 100%;
    outline: none;
    text-decoration: none;
    -ms-interpolation-mode: bicubic;
  }

  table {
    border-collapse: collapse;
    mso-table-lspace: 0pt;
    mso-table-rspace: 0pt;
  }

  /* Prevent Gmail from changing link colors */
  u + .body a {
    color: inherit;
    text-decoration: none;
  }

  /* Prevent iOS Mail from auto-scaling */
  .ios-fix {
    min-width: 100vw;
    -webkit-text-size-adjust: 100%;
  }

  /* ─── Variables ─── */
  :root {
    --bg-deep:      #0a0c0f;
    --bg-card:      #111418;
    --bg-surface:   #161b22;
    --border:       #1e2a3a;
    --accent:       #00f0ff;       /* cyan */
    --accent-dim:   #00b3bfaa;
    --accent-glow:  #00f0ff40;
    --green:        #39ff14;
    --green-dim:    #39ff1466;
    --red:          #ff3b5c;
    --text-primary: #e2e8f0;
    --text-muted:   #64748b;
    --text-dim:     #3f4f64;
  }

  body {
    background-color: var(--bg-deep);
    font-family: 'Rajdhani', sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
  }

  /* ─── Outer Wrapper ─── */
  .email-wrapper {
    max-width: 600px;
    width: 100%;
    margin: 0 auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
    position: relative;
  }

  /* ─── Scanline Overlay ─── */
  .scanlines {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 100;
    background: repeating-linear-gradient(
      0deg,
      transparent 0px,
      transparent 2px,
      rgba(0,0,0,0.15) 2px,
      rgba(0,0,0,0.15) 4px
    );
  }

  /* ─── Top Accent Bar ─── */
  .accent-bar {
    height: 3px;
    background: linear-gradient(90deg, transparent 0%, var(--accent) 30%, var(--green) 70%, transparent 100%);
    box-shadow: 0 0 12px var(--accent-glow);
  }

  /* ─── Hero Section ─── */
  .hero {
    padding: 48px 40px 36px;
    position: relative;
    text-align: center;
    background:
      radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,240,255,0.06) 0%, transparent 70%),
      var(--bg-card);
  }

  .hero-eyebrow {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--green);
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 18px;
    opacity: 0.9;
  }
  /* blinking cursor */
  .hero-eyebrow .cursor {
    display: inline-block;
    width: 8px;
    height: 12px;
    background: var(--green);
    margin-left: 4px;
    vertical-align: middle;
    animation: blink 1.1s step-end infinite;
  }
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
  }

  .hero h1 {
    font-family: 'Rajdhani', sans-serif;
    font-weight: 700;
    font-size: 42px;
    line-height: 1.1;
    letter-spacing: -1px;
    color: var(--accent);
    text-shadow: 0 0 24px var(--accent-glow), 0 0 60px rgba(0,240,255,0.1);
    margin-bottom: 6px;
  }

  .hero .glitch-sub {
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: var(--text-muted);
    letter-spacing: 2px;
  }

  /* corner brackets */
  .corner {
    position: absolute;
    width: 20px;
    height: 20px;
    border-color: var(--accent-dim);
    border-style: solid;
  }
  .corner--tl { top: 16px; left: 16px; border-width: 1px 0 0 1px; }
  .corner--tr { top: 16px; right: 16px; border-width: 1px 1px 0 0; }
  .corner--bl { bottom: 16px; left: 16px; border-width: 0 0 1px 1px; }
  .corner--br { bottom: 16px; right: 16px; border-width: 0 1px 1px 0; }

  /* ─── Divider ─── */
  .divider {
    height: 1px;
    margin: 0 40px;
    background: linear-gradient(90deg, transparent, var(--border) 20%, var(--border) 80%, transparent);
  }

  /* ─── Info Grid ─── */
  .info-grid {
    padding: 32px 40px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }

  .info-block {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 18px 20px;
    position: relative;
  }
  .info-block::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 30px; height: 2px;
    background: var(--accent);
    border-radius: 0 0 2px 0;
  }

  .info-block .label {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 6px;
  }
  .info-block .value {
    font-family: 'Rajdhani', sans-serif;
    font-weight: 600;
    font-size: 17px;
    color: var(--text-primary);
    line-height: 1.3;
  }

  /* ─── Body Copy ─── */
  .body-copy {
    padding: 4px 40px 28px;
    font-size: 15px;
    line-height: 1.7;
    color: var(--text-muted);
  }
  .body-copy .highlight {
    color: var(--accent);
    font-weight: 600;
  }

  /* ─── CTA Section ─── */
  .cta-section {
    padding: 28px 40px 36px;
    text-align: center;
  }

  .cta-btn {
    display: inline-block;
    background: transparent;
    border: 1px solid var(--accent);
    color: var(--accent);
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 3px;
    text-transform: uppercase;
    text-decoration: none;
    padding: 16px 44px;
    border-radius: 2px;
    position: relative;
    box-shadow:
      0 0 10px var(--accent-glow),
      inset 0 0 10px rgba(0,240,255,0.04);
    transition: background 0.25s, box-shadow 0.25s, color 0.25s;
  }
  .cta-btn:hover {
    background: var(--accent-glow);
    box-shadow:
      0 0 24px var(--accent-glow),
      0 0 60px rgba(0,240,255,0.12),
      inset 0 0 16px rgba(0,240,255,0.08);
    color: #fff;
  }

  .cta-sub {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 14px;
    letter-spacing: 1px;
  }

  /* ─── Warning Strip ─── */
  .warning-strip {
    margin: 0 40px 28px;
    border: 1px solid #1e2a3a;
    border-left: 3px solid var(--red);
    background: rgba(255,59,92,0.05);
    border-radius: 0 3px 3px 0;
    padding: 14px 18px;
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .warning-strip .warn-icon {
    font-family: 'Share Tech Mono', monospace;
    font-size: 14px;
    color: var(--red);
    flex-shrink: 0;
    line-height: 1.4;
  }
  .warning-strip p {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: #64748b;
    line-height: 1.6;
  }
  .warning-strip p strong {
    color: var(--red);
    font-weight: 600;
  }

  /* ─── Footer ─── */
  .footer {
    border-top: 1px solid var(--border);
    padding: 24px 40px;
    background: rgba(0,0,0,0.15);
  }
  .footer .footer-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  .footer .org {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    letter-spacing: 2px;
  }
  .footer .social-links a {
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    text-decoration: none;
    margin-left: 16px;
    letter-spacing: 1px;
    transition: color 0.2s;
  }
  .footer .social-links a:hover { color: var(--accent); }

  .footer .legal {
    font-family: 'Share Tech Mono', monospace;
    font-size: 9px;
    color: #2d3a4a;
    line-height: 1.7;
  }
  .footer .legal a {
    color: #3f5060;
    text-decoration: none;
  }
  .footer .legal a:hover { color: var(--accent); }

  /* ─── Bottom Accent Bar ─── */
  .accent-bar-bottom {
    height: 2px;
    background: linear-gradient(90deg, transparent 0%, var(--green) 40%, var(--accent) 60%, transparent 100%);
    opacity: 0.6;
  }

  /* ─── Responsive ─── */
  @media (max-width: 600px) {
    .email-wrapper {
      margin: 8px !important;
      width: calc(100% - 16px) !important;
    }
    .hero {
      padding: 32px 20px 24px !important;
    }
    .hero h1 {
      font-size: 28px !important;
      letter-spacing: -0.5px !important;
    }
    .hero-eyebrow {
      font-size: 10px !important;
      letter-spacing: 2px !important;
    }
    .glitch-sub {
      font-size: 11px !important;
    }
    .info-grid {
      grid-template-columns: 1fr !important;
      padding: 20px !important;
      gap: 12px !important;
    }
    .info-block {
      padding: 14px 16px !important;
    }
    .info-block .value {
      font-size: 15px !important;
    }
    .body-copy {
      padding: 4px 20px 24px !important;
      font-size: 14px !important;
    }
    .cta-section {
      padding: 24px 20px 32px !important;
    }
    .cta-btn {
      padding: 14px 32px !important;
      font-size: 12px !important;
      letter-spacing: 2px !important;
      display: block !important;
      width: 100% !important;
      max-width: 280px !important;
      margin: 0 auto !important;
    }
    .cta-sub {
      font-size: 9px !important;
      margin-top: 12px !important;
    }
    .warning-strip {
      margin: 0 20px 24px !important;
      padding: 12px 14px !important;
      gap: 10px !important;
    }
    .warning-strip p {
      font-size: 10px !important;
    }
    .divider {
      margin: 0 20px !important;
    }
    .footer {
      padding: 20px !important;
    }
    .footer .footer-top {
      flex-direction: column !important;
      gap: 12px !important;
      text-align: center !important;
      align-items: center !important;
    }
    .footer .social-links {
      display: flex !important;
      gap: 8px !important;
    }
    .footer .social-links a {
      margin-left: 0 !important;
    }
    .footer .legal {
      text-align: center !important;
      font-size: 8px !important;
    }
    .corner {
      width: 16px !important;
      height: 16px !important;
    }
    .corner--tl, .corner--tr { top: 12px !important; }
    .corner--bl, .corner--br { bottom: 12px !important; }
    .corner--tl, .corner--bl { left: 12px !important; }
    .corner--tr, .corner--br { right: 12px !important; }
  }
</style>
</head>
<body class="body">

<!-- Outer table wrapper for email client compatibility -->
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #0a0c0f;">
  <tr>
    <td align="center" style="padding: 20px 0;">

<div class="email-wrapper">
  <div class="scanlines"></div>

  <!-- Top Accent -->
  <div class="accent-bar"></div>

  <!-- Hero -->
  <div class="hero">
    <div class="corner corner--tl"></div>
    <div class="corner corner--tr"></div>
    <div class="corner corner--bl"></div>
    <div class="corner corner--br"></div>

    <p class="hero-eyebrow">ACCESS GRANTED <span class="cursor"></span></p>
    <h1>YOU'RE IN.</h1>
    <p class="glitch-sub">// INVITATION ONLY — DO NOT FORWARD</p>
  </div>

  <div class="divider"></div>

  <!-- Event Details Grid -->
  <div class="info-grid">
    <div class="info-block">
      <p class="label">Event</p>
      <p class="value">{event_name}</p>
    </div>
    <div class="info-block">
      <p class="label">Date</p>
      <p class="value">{event_date_range}</p>
    </div>
    <div class="info-block">
      <p class="label">Time</p>
      <p class="value">{event_time}</p>
    </div>
    <div class="info-block">
      <p class="label">Location</p>
      <p class="value">{event_location}</p>
    </div>
  </div>

  <!-- Body -->
  <div class="body-copy">
    <p>
      Your invitation to <span class="highlight">{event_name}</span> has been confirmed.
      This is an invite-only gathering — zero public tickets, zero livestream.
      If you're reading this, you were hand-picked.
    </p>
    <br/>
    <p>
      Expect live red-team demos, zero-day war stories, and a CTF built to
      separate the curious from the capable. Networking starts at the door.
    </p>
  </div>

  <!-- Warning Strip -->
  <div class="warning-strip">
    <span class="warn-icon">⚠</span>
    <p><strong>OPSEC NOTICE:</strong> This invite is tied to your identity token. Forwarding or sharing this link will invalidate your access and revoke your entry. Confirm only through the official portal.</p>
  </div>

  <!-- CTA -->
  <div class="cta-section">
    <a href="{confirmation_url}" class="cta-btn">Confirm Access</a>
    <p class="cta-sub">Link expires in 72 hours · Single-use token</p>
  </div>

  <!-- Footer -->
  <div class="footer">
    <div class="footer-top">
      <span class="org">CYBERX // RED TEAM COLLECTIVE</span>
      <div class="social-links">
        <a href="#">TWITTER</a>
        <a href="#">DISCORD</a>
        <a href="#">GITHUB</a>
      </div>
    </div>
    <p class="legal">
      You are receiving this because you were personally invited to {event_name}.<br/>
      Questions? Contact us at events@cyberxredteam.org
    </p>
  </div>

  <!-- Bottom Accent -->
  <div class="accent-bar-bottom"></div>
</div>

    </td>
  </tr>
</table>

</body>
</html>""",
    "text_content": """ACCESS GRANTED

YOU'RE IN.

Your invitation to {event_name} has been confirmed.

EVENT DETAILS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event: {event_name}
Date: {event_date_range}
Time: {event_time}
Location: {event_location}

This is an invite-only gathering — zero public tickets, zero livestream. If you're reading this, you were hand-picked.

Expect live red-team demos, zero-day war stories, and a CTF built to separate the curious from the capable. Networking starts at the door.

⚠ OPSEC NOTICE: This invite is tied to your identity token. Forwarding or sharing this link will invalidate your access and revoke your entry. Confirm only through the official portal.

CONFIRM YOUR ACCESS:
{confirmation_url}

Link expires in 14 days · Single-use token

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CYBERX // RED TEAM COLLECTIVE

You are receiving this because you were personally invited to {event_name}.
Questions? Contact us at events@cyberxredteam.org
""",
    "available_variables": [
        "event_name",
        "event_date_range",
        "event_time",
        "event_location",
        "confirmation_url",
        "first_name",
        "last_name",
        "email"
    ],
    "is_active": True,
    "is_system": True
}


def escape_template_for_python_format(html: str, subject: str, template_vars: list) -> tuple:
    """
    Escape CSS/HTML braces while preserving template variables for Python's .format().

    Python's .format() treats ALL curly braces as template variables. This causes issues
    when HTML templates contain CSS with braces. This function escapes all braces except
    the specified template variables.

    Args:
        html: HTML content with CSS
        subject: Subject line
        template_vars: List of variable names to preserve (e.g., ['event_name', 'confirmation_url'])

    Returns:
        Tuple of (escaped_html, escaped_subject)
    """
    # Temporarily replace template variables with placeholders
    placeholders = {}
    for i, var in enumerate(template_vars):
        placeholder = f'__TEMPLATE_VAR_{i}__'
        placeholders[placeholder] = '{' + var + '}'
        html = html.replace('{' + var + '}', placeholder)
        subject = subject.replace('{' + var + '}', placeholder)

    # Escape all remaining braces by doubling them (for Python .format())
    html = html.replace('{', '{{').replace('}', '}}')
    subject = subject.replace('{', '{{').replace('}', '}}')

    # Restore template variables (unescape them)
    for placeholder, original in placeholders.items():
        html = html.replace(placeholder, original)
        subject = subject.replace(placeholder, original)

    return html, subject


async def update_invite_template():
    """Update or create the hacker-themed invitation template."""
    async with AsyncSessionLocal() as session:
        # Escape CSS braces while preserving template variables
        template_vars = HACKER_INVITE_TEMPLATE["available_variables"]
        escaped_html, escaped_subject = escape_template_for_python_format(
            HACKER_INVITE_TEMPLATE["html_content"],
            HACKER_INVITE_TEMPLATE["subject"],
            template_vars
        )

        # Create template data with escaped content
        template_data = {k: v for k, v in HACKER_INVITE_TEMPLATE.items() if k != "name"}
        template_data["html_content"] = escaped_html
        template_data["subject"] = escaped_subject

        # Check if invite template exists
        result = await session.execute(
            select(EmailTemplate).where(EmailTemplate.name == "invite")
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing template
            await session.execute(
                update(EmailTemplate)
                .where(EmailTemplate.name == "invite")
                .values(**template_data)
            )
            print("✓ Updated existing 'invite' template with hacker theme (CSS braces escaped)")
        else:
            # Create new template
            template = EmailTemplate(name=HACKER_INVITE_TEMPLATE["name"], **template_data)
            session.add(template)
            print("✓ Created new 'invite' template with hacker theme (CSS braces escaped)")

        await session.commit()
        print("\n✓ Hacker-themed invitation template ready!")
        print("\nAvailable variables:")
        for var in HACKER_INVITE_TEMPLATE["available_variables"]:
            print(f"  - {var}")


if __name__ == "__main__":
    asyncio.run(update_invite_template())
