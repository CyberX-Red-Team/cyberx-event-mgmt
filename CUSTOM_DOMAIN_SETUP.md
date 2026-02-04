# Custom Domain Setup for Render

Complete guide for configuring a custom domain with your Render deployment.

---

## 🌐 Overview

By default, your app is available at:
```
https://cyberx-event-mgmt.onrender.com
```

With a custom domain, you can use:
```
https://events.cyberxredteam.org
```

**Benefits:**
- ✅ Professional appearance
- ✅ Easier to remember
- ✅ Better for branding
- ✅ Automatic SSL (free via Let's Encrypt)
- ✅ No extra cost with Render

---

## 🚀 Quick Setup (5 minutes)

### Step 1: Add Domain to Render

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select your `cyberx-event-mgmt` web service
3. Click **Settings** tab
4. Scroll down to **Custom Domains**
5. Click **Add Custom Domain**
6. Enter your domain:
   ```
   events.cyberxredteam.org
   ```
7. Click **Save**

Render will show DNS instructions.

### Step 2: Configure DNS

Add a **CNAME record** in your DNS provider:

```
Type:   CNAME
Name:   events
Value:  cyberx-event-mgmt.onrender.com
TTL:    3600 (or Auto)
```

### Step 3: Wait for Verification

- DNS propagation: 5-60 minutes (usually < 15 minutes)
- SSL certificate: Automatic (5-15 minutes after DNS propagates)
- Status in Render: Changes from "Pending" → "Verified" ✅

### Step 4: Update Environment Variables

In Render dashboard, update these environment variables:

```env
FRONTEND_URL=https://events.cyberxredteam.org
ALLOWED_HOSTS=events.cyberxredteam.org,cyberx-event-mgmt.onrender.com
```

Click **Save Changes** → Render will redeploy automatically.

### Step 5: Test

```bash
# Test your custom domain
curl https://events.cyberxredteam.org/health

# Should return:
# {"status":"healthy","timestamp":"..."}

# Test in browser
open https://events.cyberxredteam.org/api/docs
```

---

## 📝 DNS Configuration by Provider

### Cloudflare

1. **Log in to Cloudflare**
2. Select your domain (`cyberxredteam.org`)
3. Go to **DNS** → **Records**
4. Click **Add record**

**Settings:**
```
Type:           CNAME
Name:           events
Target:         cyberx-event-mgmt.onrender.com
Proxy status:   DNS only (gray cloud, not orange!)
TTL:            Auto
```

**Important:** Set to **DNS only** (gray cloud), not proxied!
- Orange cloud = Cloudflare proxy (breaks SSL verification)
- Gray cloud = DNS only (works with Render SSL)

**Optional:** After SSL is verified, you can enable proxy (orange cloud) for:
- Cloudflare's DDoS protection
- Page caching
- Analytics

### Google Domains (Legacy) / Google Cloud DNS

1. **Log in to Google Domains** or **Google Cloud Console**
2. Select your domain
3. Go to **DNS** settings
4. Click **Manage custom records**

**Add record:**
```
Host name:      events
Type:           CNAME
TTL:            3600
Data:           cyberx-event-mgmt.onrender.com
```

### GoDaddy

1. **Log in to GoDaddy**
2. Go to **My Products** → **DNS**
3. Find your domain and click **Manage DNS**
4. Scroll to **Records** section
5. Click **Add**

**Settings:**
```
Type:           CNAME
Name:           events
Value:          cyberx-event-mgmt.onrender.com
TTL:            1 Hour (or Custom: 3600 seconds)
```

### Namecheap

1. **Log in to Namecheap**
2. Go to **Domain List**
3. Click **Manage** next to your domain
4. Go to **Advanced DNS** tab
5. Click **Add New Record**

**Settings:**
```
Type:           CNAME Record
Host:           events
Value:          cyberx-event-mgmt.onrender.com
TTL:            Automatic
```

### AWS Route 53

1. **Log in to AWS Console**
2. Go to **Route 53** → **Hosted Zones**
3. Select your domain
4. Click **Create Record**

**Settings:**
```
Record name:    events
Record type:    CNAME
Value:          cyberx-event-mgmt.onrender.com
TTL:            300
Routing policy: Simple routing
```

### DigitalOcean

1. **Log in to DigitalOcean**
2. Go to **Networking** → **Domains**
3. Select your domain
4. Under **CNAME Records**, click **Add**

**Settings:**
```
Hostname:       events
Will Direct To: cyberx-event-mgmt.onrender.com
TTL:            3600
```

---

## 🔐 SSL Certificate (Automatic)

Render automatically provisions SSL certificates via **Let's Encrypt**.

### How It Works

1. **DNS verification**
   - Render checks if your CNAME points to them
   - Usually takes 5-15 minutes after DNS propagates

2. **Certificate issuance**
   - Let's Encrypt issues free SSL certificate
   - Automatic renewal every 90 days
   - Zero configuration needed!

3. **HTTPS enforcement**
   - HTTP → HTTPS redirect automatic
   - TLS 1.2 and 1.3 supported
   - A+ SSL rating

### Verification Status

Check status in Render dashboard:
- ⏳ **Pending** - Waiting for DNS propagation
- ⚠️ **Failed** - DNS configuration issue
- ✅ **Verified** - SSL active, domain ready!

### Troubleshooting SSL

**Issue: Stuck on "Pending"**

Check DNS propagation:
```bash
# Check if CNAME is set correctly
dig events.cyberxredteam.org CNAME

# Should show:
# events.cyberxredteam.org. 3600 IN CNAME cyberx-event-mgmt.onrender.com.
```

**Issue: "Failed" status**

1. Verify CNAME record is correct
2. If using Cloudflare, disable proxy (gray cloud)
3. Wait 5 minutes and try "Retry" in Render
4. Check DNS propagation: https://dnschecker.org

**Issue: SSL certificate expired**

- Render auto-renews every 90 days
- If expired, contact Render support
- Usually indicates a DNS issue

---

## 🔄 Multiple Domains (Optional)

You can add multiple domains to the same service:

**Example:**
```
Primary:        events.cyberxredteam.org
Alternative:    cyberx-events.com
Subdomain:      app.cyberxredteam.org
```

**Why multiple domains?**
- Brand alternatives
- Old domain redirect
- Regional domains
- Development/staging

**How to add:**
1. Repeat "Add Custom Domain" for each
2. Configure DNS for each domain
3. Update `ALLOWED_HOSTS` with all domains:
   ```env
   ALLOWED_HOSTS=events.cyberxredteam.org,cyberx-events.com,app.cyberxredteam.org,cyberx-event-mgmt.onrender.com
   ```

---

## 🌍 Using Root/Apex Domain

**Example:** `cyberxredteam.org` (without subdomain)

### Why Subdomain is Recommended

**Subdomain (events.cyberxredteam.org):**
- ✅ Easy CNAME setup
- ✅ Faster DNS propagation
- ✅ Better for CDN/proxy
- ✅ Flexible (can move services)

**Root domain (cyberxredteam.org):**
- ⚠️ Requires A records (IP addresses)
- ⚠️ Less flexible
- ⚠️ IPs can change (though rare)
- ✅ Looks cleaner (shorter URL)

### Root Domain Setup

If you must use root/apex domain:

1. **In Render dashboard:**
   - Add `cyberxredteam.org` as custom domain
   - Render shows IP addresses

2. **In DNS provider:**
   - Add **A records** with provided IPs:
     ```
     Type:   A
     Name:   @ (or leave blank)
     Value:  <IP from Render>
     TTL:    3600
     ```
   - You'll need to add multiple A records (Render provides 2-3 IPs)

3. **ANAME/ALIAS (if supported):**
   - Some DNS providers (Cloudflare, AWS Route 53) support ANAME/ALIAS
   - These work like CNAME for root domains
   - Preferred over A records if available

---

## 🔍 Verification & Testing

### Check DNS Propagation

```bash
# Check CNAME record
dig events.cyberxredteam.org CNAME

# Check from multiple locations
# Use: https://dnschecker.org

# Check with specific DNS server
dig @8.8.8.8 events.cyberxredteam.org CNAME
```

### Test HTTP/HTTPS

```bash
# Test HTTP (should redirect to HTTPS)
curl -I http://events.cyberxredteam.org

# Should return:
# HTTP/1.1 301 Moved Permanently
# Location: https://events.cyberxredteam.org/

# Test HTTPS
curl -I https://events.cyberxredteam.org

# Should return:
# HTTP/2 200
```

### Test SSL Certificate

```bash
# View certificate details
openssl s_client -connect events.cyberxredteam.org:443 -servername events.cyberxredteam.org < /dev/null

# Check SSL rating
# Use: https://www.ssllabs.com/ssltest/
```

### Test Application

```bash
# Health check
curl https://events.cyberxredteam.org/health

# API docs
open https://events.cyberxredteam.org/api/docs

# Login page
open https://events.cyberxredteam.org
```

---

## 🔧 Updating Email Templates

After setting up your custom domain, update SendGrid email templates:

**Variables to update:**
- `{{frontend_url}}` → `https://events.cyberxredteam.org`
- Links in templates → Use custom domain
- "Confirm email" links → Custom domain
- "Reset password" links → Custom domain

**In Render environment variables:**
```env
FRONTEND_URL=https://events.cyberxredteam.org
```

This ensures all generated links use your custom domain.

---

## 📧 Email Domain (Optional)

Consider matching email domain to web domain:

**Current:**
```
Website:   events.cyberxredteam.org
Email:     noreply@example.com (mismatched!)
```

**Better:**
```
Website:   events.cyberxredteam.org
Email:     noreply@cyberxredteam.org (matched!)
```

**Why match?**
- ✅ Better sender reputation
- ✅ Professional appearance
- ✅ Fewer spam flags
- ✅ Brand consistency

**Setup:**
1. Verify domain with SendGrid
2. Update `SENDGRID_FROM_EMAIL` environment variable
3. Update email templates

---

## 🛠️ Troubleshooting

### DNS Not Propagating

**Symptoms:** Can't access custom domain after 1 hour

**Check:**
```bash
# Check if record exists
dig events.cyberxredteam.org

# Check from different DNS server
dig @8.8.8.8 events.cyberxredteam.org
dig @1.1.1.1 events.cyberxredteam.org
```

**Solutions:**
1. Wait 24-48 hours (worst case)
2. Clear local DNS cache:
   ```bash
   # macOS
   sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

   # Linux
   sudo systemd-resolve --flush-caches

   # Windows
   ipconfig /flushdns
   ```
3. Try incognito/private browsing
4. Check with different device/network

### SSL Certificate Not Issuing

**Symptoms:** Domain verified but no HTTPS

**Check Render dashboard:**
- Status should be "Verified" with green checkmark
- If "Failed", click "Retry"

**Common causes:**
1. Cloudflare proxy enabled (orange cloud)
   - Solution: Disable proxy (gray cloud)
2. CAA DNS record blocking Let's Encrypt
   - Solution: Add CAA record allowing Let's Encrypt
3. Domain recently transferred
   - Solution: Wait 24 hours

**Manual check:**
```bash
# Check if SSL works
curl -I https://events.cyberxredteam.org

# Should NOT show certificate errors
```

### Domain Works But App Doesn't Load

**Symptoms:** Domain accessible but shows error or old content

**Check:**
1. Environment variables updated?
   ```env
   FRONTEND_URL=https://events.cyberxredteam.org
   ALLOWED_HOSTS=events.cyberxredteam.org,...
   ```
2. Service redeployed after env var changes?
3. Check Render logs for errors

**Solution:**
- Trigger manual redeploy in Render
- Check logs for any errors

### Browser Shows "Not Secure" Warning

**Symptoms:** Custom domain works but browser warns about SSL

**Check:**
1. Is domain fully verified in Render?
2. Is certificate issued? (check Render dashboard)
3. Try in different browser/incognito

**Usually caused by:**
- DNS/SSL still propagating (wait 15 minutes)
- Browser cached old certificate
- Mixed content (HTTP resources on HTTPS page)

---

## 📱 Mobile App / API Clients

If you have mobile apps or API clients:

**Update base URLs:**
```javascript
// Before
const API_BASE_URL = "https://cyberx-event-mgmt.onrender.com";

// After
const API_BASE_URL = "https://events.cyberxredteam.org";
```

**Consider:**
- Keep Render subdomain as fallback
- Implement retry with fallback URL
- Update app store listings with new domain

---

## 🔐 Security Best Practices

### DNS Security

**Enable DNSSEC** (if your DNS provider supports it):
- Prevents DNS spoofing
- Adds cryptographic signatures
- Supported by: Cloudflare, Google Cloud DNS, Route 53

### CAA Records

**Add CAA record** to specify allowed certificate authorities:

```
Type:   CAA
Name:   events (or @)
Value:  0 issue "letsencrypt.org"
```

This prevents other CAs from issuing certificates for your domain.

### CORS Configuration

**Update CORS settings** in your app to allow custom domain:

In `app/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://events.cyberxredteam.org",
        "https://cyberx-event-mgmt.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 📊 Monitoring

### Domain Health

**Monitor:**
- SSL certificate expiration (Render auto-renews)
- DNS resolution
- Domain registration expiration
- SSL rating (SSLLabs.com)

**Set reminders:**
- Domain renewal: 30 days before expiration
- Review SSL config: Quarterly
- Check DNS propagation: After any changes

### Uptime Monitoring

**Use external monitoring:**
- UptimeRobot (free)
- Pingdom
- StatusCake
- Render's built-in monitoring

**Monitor endpoints:**
- `https://events.cyberxredteam.org/health`
- `https://events.cyberxredteam.org/api/docs`

---

## 📋 Checklist

### Initial Setup
```
□ Add custom domain in Render dashboard
□ Configure CNAME record in DNS provider
□ Wait for DNS propagation (5-60 minutes)
□ Verify SSL certificate issued (green checkmark)
□ Update FRONTEND_URL environment variable
□ Update ALLOWED_HOSTS environment variable
□ Redeploy service
□ Test custom domain access
□ Test HTTPS and certificate
□ Update email templates
□ Update any API clients/mobile apps
```

### Post-Setup
```
□ Set domain renewal reminder
□ Enable DNSSEC (if available)
□ Add CAA record for Let's Encrypt
□ Set up uptime monitoring
□ Update documentation with new domain
□ Notify users of domain change (if applicable)
```

---

## 💡 Tips

1. **Use subdomain** - Easier than root domain
2. **Cloudflare users** - Disable proxy initially (gray cloud)
3. **Match email domain** - Better for deliverability
4. **Keep Render subdomain** - As fallback in ALLOWED_HOSTS
5. **Test thoroughly** - Check all endpoints and flows
6. **Monitor SSL** - Though Render auto-renews
7. **Document domain** - Update README and docs

---

## 🆘 Support

**Render Support:**
- Dashboard → Help → Contact Support
- Community: https://community.render.com
- Status: https://status.render.com

**DNS Provider Support:**
- Cloudflare: https://support.cloudflare.com
- Google Domains: https://support.google.com/domains
- GoDaddy: https://www.godaddy.com/help

---

**Last Updated:** 2026-02-03
