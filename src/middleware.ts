import { NextRequest, NextResponse } from "next/server";

/**
 * Zamyká `/interni/*` (novinářský nástroj, Fáze 6) za HTTP Basic Auth.
 *
 * Bez obou proměnných (`INTERNAL_TOOL_USER`, `INTERNAL_TOOL_PASSWORD`) je
 * route uzamčená napevno — fail closed, ne fail open. Data pod `/interni`
 * jsou pásmo NLI 0,50–0,80 (`pipeline/journalist_tool.py`), které nikdy
 * neprošlo tribunálem — nesmí uniknout bez zámku jen proto, že v prostředí
 * chybí konfigurace.
 */
export function middleware(request: NextRequest) {
  const user = process.env.INTERNAL_TOOL_USER;
  const password = process.env.INTERNAL_TOOL_PASSWORD;

  if (!user || !password) {
    return new NextResponse("Interní nástroj není nakonfigurován.", { status: 503 });
  }

  const auth = request.headers.get("authorization");
  if (auth) {
    const [scheme, encoded] = auth.split(" ");
    if (scheme === "Basic" && encoded) {
      const decoded = Buffer.from(encoded, "base64").toString("utf-8");
      const separatorIndex = decoded.indexOf(":");
      const suppliedUser = decoded.slice(0, separatorIndex);
      const suppliedPassword = decoded.slice(separatorIndex + 1);
      if (suppliedUser === user && suppliedPassword === password) {
        return NextResponse.next();
      }
    }
  }

  return new NextResponse("Vyžadováno přihlášení.", {
    status: 401,
    // HTTP header hodnoty musí být ByteString (Latin-1) — bez diakritiky, jinak middleware spadne.
    headers: { "WWW-Authenticate": 'Basic realm="Interni nastroj Nezalzeme.cz"' },
  });
}

export const config = {
  matcher: ["/interni/:path*"],
};
