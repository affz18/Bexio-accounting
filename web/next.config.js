/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Wir deployen den Bot weiterhin separat auf Railway. Die Web-App kann
  // auf Vercel laufen oder auch in einem zweiten Railway-Service.
  experimental: {
    // Server Actions sind seit Next 14 stable, aber wir lassen das offen
    // falls wir spaeter Tweaks brauchen
  },
};

module.exports = nextConfig;
