# Step 1: Base it on some existing image
FROM rqi14/perplexica-app:slim

# Step 2: Read two args, NEXT_PUBLIC_WS_URL and NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_API_URL

# Step 3: Loop through .js files and replace placeholders
RUN find /home/perplexica/.next/static/chunks -type f -name '*.js' -exec sed -i 's|__NEXT_PUBLIC_WS_URL__|'"${NEXT_PUBLIC_WS_URL}"'|g; s|__NEXT_PUBLIC_API_URL__|'"${NEXT_PUBLIC_API_URL}"'|g' {} +