import Console from "@/components/Console";

/**
 * The console is one full-bleed view. Everything interactive lives in the client
 * component; this stays a server component so the page shell is static.
 */
export default function Page() {
  return <Console />;
}
