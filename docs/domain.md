# Project domain

The project website is **https://multibioarena.fun/**. The `www.multibioarena.fun` hostname is attached to the same frontend project and configured to redirect permanently to the apex hostname.

**Verified live on 2026-09-11:** public DNS matches the configured A/CNAME records, Vercel reports both hostnames valid, and the issued certificate serves HTTPS successfully. The apex homepage and `/api/health` return HTTP 200; `www` returns HTTP 308 to the apex. The existing [Vercel preview](https://multi-bio-arena.vercel.app/) also remains available. A 390-pixel mobile browser check showed all three Bios, no horizontal overflow, no page errors and no API write or audience requests.

## DNS records

The domain currently uses Namecheap BasicDNS. In Namecheap, open **Domain List → Manage → Advanced DNS → Host Records → Add New Record**.

| Type | Host | Value | TTL |
| --- | --- | --- | --- |
| A Record | `@` | `216.198.79.1` | Automatic |
| CNAME Record | `www` | `423ee16909c62e18.vercel-dns-017.com` | Automatic |

These values were read from Vercel's domain configuration API for this project, rather than copied from an unrelated deployment. The API also lists `64.29.17.1` as an equally ranked IPv4 option; the table uses the first recommended value. Recheck the project's Domains settings if Vercel later changes its recommendations.

Update any conflicting website records for the same `@` or `www` host. Keep the existing nameservers and unrelated email/verification records. Save the two records, then wait for Vercel's Domains page to show a valid configuration and for HTTPS issuance to complete. Domain ownership verification alone does not mean the DNS or certificate is ready.

After activation, verify the homepage and `/api/health` on the custom domain and confirm that `www` redirects to the apex. The frontend still reads the same persistent paper backend; attaching a domain does not reset brains, positions or learning. It does not enable live execution, voting or the hourly challenge.

Official setup references: [Namecheap A records](https://www.namecheap.com/support/knowledgebase/article.aspx/319/2237/how-can-i-set-up-an-a-address-record-for-my-domain/), [Namecheap CNAME records](https://www.namecheap.com/support/knowledgebase/article.aspx/9646/2237/how-to-create-a-cname-record-for-your-domain/), and [Vercel custom domains](https://vercel.com/docs/domains/working-with-domains/add-a-domain).
