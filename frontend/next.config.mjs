/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
    typedRoutes: true
  },
  async redirects() {
    return [
      {
        source: '/settings',
        destination: '/dashboard/settings',
        permanent: true,
      },
      {
        source: '/admin',
        destination: '/dashboard/admin',
        permanent: true,
      },
    ];
  },
  async headers() {
    // Content-Security-Policy (аудит безопасности): защита в глубину от XSS для
    // приложения с ПД. В prod-сборке Next не использует eval — CSP строгий; в
    // dev webpack-HMR требует 'unsafe-eval' + websocket + прямой origin API
    // (localhost:8000), поэтому в dev CSP мягче. script/style-src держат
    // 'unsafe-inline' (Next инлайнит bootstrap-скрипты без nonce). Разрешён
    // домен Яндекс.Метрики (mc.yandex.ru) — аналитика, гейтится cookie-согласием.
    const isDev = process.env.NODE_ENV !== 'production';
    const metrika = 'https://mc.yandex.ru';
    const scriptExtra = isDev ? " 'unsafe-eval'" : '';
    const connectExtra = isDev ? ' http://localhost:8000 ws://localhost:* http://127.0.0.1:8000' : '';
    const csp = [
      "default-src 'self'",
      `script-src 'self' 'unsafe-inline'${scriptExtra} ${metrika}`,
      "style-src 'self' 'unsafe-inline'",
      `img-src 'self' data: https: ${metrika}`,
      "font-src 'self' data:",
      `connect-src 'self' ${metrika}${connectExtra}`,
      `frame-src ${metrika}`,
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ].join('; ');
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Content-Security-Policy', value: csp },
        ],
      },
    ];
  },
};

export default nextConfig;
