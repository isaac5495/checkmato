import "./globals.css";

export const metadata = {
  title: "CheckMato — fact-check AI-written documents",
  description:
    "Upload an AI-drafted case study, document or article: CheckMato extracts every verifiable claim and shows line-precise evidence before you publish.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
