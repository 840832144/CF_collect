#!/system/bin/sh
for h in storage.googleapis.com firebaseinstallations.googleapis.com d2rargdj3vlbg6.cloudfront.net www.google.com; do
  if timeout 6 nc -w4 -z "$h" 443 >/dev/null 2>&1; then echo "$h OK"; else echo "$h FAIL"; fi
done
