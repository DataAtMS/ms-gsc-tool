# Service Account Setup for Different Domain

## Problem
Your service account `gsc-reader@gsc-api-v1-485110.iam.gserviceaccount.com` is currently added to a different Search Console property than the one you're trying to access.

## Solution Options

### Option 1: Add Service Account to Your Target Property (RECOMMENDED)

1. **Go to your target Search Console property:**
   - Visit [Google Search Console](https://search.google.com/search-console)
   - Select the property/domain you want to pull data from
   - If you don't see it, add it first (Settings → Add Property)

2. **Add the service account:**
   - Go to **Settings** → **Users and permissions**
   - Click **Add user**
   - Enter: `gsc-reader@gsc-api-v1-485110.iam.gserviceaccount.com`
   - Select permission level: **Full** (or **Restricted** if you prefer)
   - Click **Add**

3. **Wait a few minutes** for permissions to propagate

4. **Test in the app:**
   - Use the correct domain format for that property
   - Try pulling data again

### Option 2: Use the Domain That's Already Connected

If you want to use the property that's already connected:

1. **Find out which property the service account has access to:**
   - Check the Search Console property where you added the service account
   - Note the exact domain format (e.g., `sc-domain:example.com` or `https://example.com/`)

2. **Use that domain in the app:**
   - Enter the domain format that matches the connected property
   - The app should now work

### Option 3: Create a New Service Account (If you need separate access)

If you need to keep the current service account for the other domain and need access to a different one:

1. **Create a new service account in Google Cloud:**
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Select project: `gsc-api-v1-485110`
   - Go to **IAM & Admin** → **Service Accounts**
   - Click **Create Service Account**
   - Name it (e.g., `gsc-reader-domain2`)
   - Grant it the **Search Console API** access

2. **Download the JSON key:**
   - Click on the new service account
   - Go to **Keys** tab
   - Click **Add Key** → **Create new key** → **JSON**
   - Save the file

3. **Add to Search Console:**
   - Go to your target Search Console property
   - Settings → Users and permissions
   - Add the new service account email

4. **Update your secrets:**
   - Replace the service account credentials in `.streamlit/secrets.toml` (local)
   - Update Streamlit Cloud secrets with the new credentials

## Finding Your Property Format

To find the correct domain format:

1. **Go to Search Console**
2. **Look at the property URL or name:**
   - If it shows `https://example.com/` → Use `https://example.com/` in the app
   - If it shows `sc-domain:example.com` → Use `sc-domain:example.com` in the app
   - If it shows just `example.com` → Try both formats

## Quick Test

After adding the service account to your target property:

1. **Wait 2-3 minutes** for permissions to propagate
2. **Restart your Streamlit app**
3. **Try pulling data with the correct domain format**
4. **Check the error message** - the updated code will tell you exactly what's wrong

## Common Issues

**"Permission denied" even after adding:**
- Wait a few more minutes (can take up to 5 minutes)
- Double-check the email address matches exactly
- Make sure you added it to the correct property

**"Property not found":**
- Try the other domain format (`sc-domain:` vs `https://`)
- Check for typos in the domain
- Verify the property exists in Search Console

**Multiple properties:**
- You can add the same service account to multiple properties
- Just repeat the "Add user" process for each property you need access to
