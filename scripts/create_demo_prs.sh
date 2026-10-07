#!/usr/bin/env bash
# Publishes the demo repository and opens its pull requests on YOUR GitHub account.
# Prerequisites: `gh` installed and `gh auth login` completed. The repository is created PUBLIC because the
# dashboard connects to public repositories only; it contains only sample code (no real secrets).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/Downloads/codewarden-demo-shop}"
REPO_NAME="${1:-codewarden-demo-shop}"

command -v gh >/dev/null || { echo "Install the GitHub CLI first: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Log in first: gh auth login"; exit 1; }
cd "$REPO_DIR"

OWNER="$(gh api user -q .login)"
echo "Will create https://github.com/$OWNER/$REPO_NAME (public) and open 6 pull requests."
read -r -p "Continue? [y/N] " ok
[[ "$ok" == "y" || "$ok" == "Y" ]] || { echo "Cancelled."; exit 0; }

if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "$OWNER/$REPO_NAME" --public --source=. --remote=origin \
    --description "Sample repository for demonstrating CodeWarden pull request reviews" --push
fi

pr() {  # branch, title, body
  git push -u origin "$1"
  gh pr create --base main --head "$1" --title "$2" --body "$3" || echo "(PR for $1 may already exist)"
}

pr feature/checkout-coupons "Add checkout with coupons" \
"Adds a checkout flow that applies coupon codes and charges the payment provider, plus a cancel-order helper."
pr feature/upload-endpoint "Add file upload and avatar fetch endpoint" \
"Lets signed-in users upload files and fetch remote avatars, and adds a small filter-expression parser."
pr chore/order-helpers "Tidy order helpers and add a test" \
"Documents order_total, adds order_count, and covers the empty-cart case with a test. No behaviour change."
pr fix/refund-status "Add refund status lookup" \
"Adds refund_status(request, order_id) so customers can see where a refund stands."
pr feature/profile-endpoint "Add profile lookup" \
"Adds get_profile(request) returning the signed-in user's name and email."
pr feature/invoices "Add invoice lookup" \
"Adds get_invoice(request, invoice_id) for the billing page."

echo
echo "Done. Connect this repository in the dashboard:  https://github.com/$OWNER/$REPO_NAME"
