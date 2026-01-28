# GSC Data Pulling - Fix Guide

## Issues Found & Fixed

### 1. **Silent Error Handling** ✅ FIXED
- **Problem:** Errors were being swallowed silently - functions returned `None` or `[]` without showing what went wrong
- **Fix:** Added error messages to all functions, now returns `(result, error_message)` tuples

### 2. **No Data Validation** ✅ FIXED
- **Problem:** Code continued even when no data was fetched
- **Fix:** Added checks to validate data exists before proceeding

### 3. **Poor Error Messages** ✅ FIXED
- **Problem:** Generic error messages didn't help debug
- **Fix:** Added specific error messages for common issues (403, 404, permission errors)

## How to Fix Your Setup

### For Local Development:

1. **Check your `.streamlit/secrets.toml` file:**
   ```bash
   cat .streamlit/secrets.toml
   ```
   
   Make sure it has all required fields:
   ```toml
   [GOOGLE_SERVICE_ACCOUNT]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "your-private-key-id"
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "your-service-account@project.iam.gserviceaccount.com"
   client_id = "your-client-id"
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
   ```

2. **Verify service account has Search Console access:**
   - Go to [Google Search Console](https://search.google.com/search-console)
   - Select your property
   - Go to Settings → Users and permissions
   - Add your service account email (from `client_email` in secrets) as a user
   - Grant "Full" or "Restricted" access

3. **Check domain format:**
   - Try both formats:
     - `sc-domain:example.com` (for domain properties)
     - `https://example.com/` (for URL prefix properties)
   - The error message will now tell you which format is correct

### For Streamlit Cloud:

1. **Check your Streamlit Cloud secrets:**
   - Go to your app settings → Secrets
   - Verify `GOOGLE_SERVICE_ACCOUNT` section exists with all fields
   - Make sure `private_key` has `\n` for line breaks (not actual newlines)

2. **Verify service account access:**
   - Same as local - add service account email to Search Console property

## Testing the Fix

After updating the code:

1. **Restart your Streamlit app:**
   ```bash
   # Stop current app (Ctrl+C)
   streamlit run app.py
   ```

2. **Try pulling data:**
   - Enter your domain
   - Click "Pull GSC Data"
   - **You should now see specific error messages** if something is wrong

3. **Common errors you might see:**

   **"Permission denied"**
   - Fix: Add service account email to Search Console property

   **"Property not found"**
   - Fix: Check domain format (try the other format)

   **"No data returned"**
   - Fix: Check date range, property access, or try a different property

   **"Error reading secrets"**
   - Fix: Check your `.streamlit/secrets.toml` syntax

## What Changed in the Code

1. `authenticate()` now returns `(creds, error_message)` instead of just `creds`
2. `fetch_gsc_data()` now returns `(rows, error_message)` instead of just `rows`
3. Added validation to check if data was actually fetched
4. Added specific error messages for common issues
5. Added data count display when successful

## Next Steps

1. **Pull the updated code:**
   ```bash
   git pull
   ```

2. **Test locally first** to see the new error messages

3. **Fix any credential/permission issues** based on the error messages

4. **Push to Streamlit Cloud** once local is working

The app will now tell you exactly what's wrong instead of failing silently!
