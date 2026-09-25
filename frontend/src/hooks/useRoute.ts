import { useCallback, useEffect, useState } from "react";

export type Route = "landing" | "chat" | "architecture";

function routeFromPath(pathname: string): Route {
  if (pathname.startsWith("/chat")) return "chat";
  if (pathname.startsWith("/architecture")) return "architecture";
  return "landing";
}

/** Small routing (/, /chat, /architecture) on the History API; small enough that a router dependency is not worth adding. */
export function useRoute(): [Route, (to: Route, options?: { replace?: boolean }) => void] {
  const [route, setRoute] = useState<Route>(() => routeFromPath(window.location.pathname));

  useEffect(() => {
    const onPop = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((to: Route, options?: { replace?: boolean }) => {
    const path = to === "chat" ? "/chat" : to === "architecture" ? "/architecture" : "/";
    if (options?.replace) window.history.replaceState(null, "", path);
    else window.history.pushState(null, "", path);
    setRoute(to);
  }, []);

  return [route, navigate];
}
