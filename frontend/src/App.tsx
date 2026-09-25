import { useCallback, useEffect } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ChatView } from "@/components/chat/ChatView";
import { useChat } from "@/hooks/useChat";
import { useRoute } from "@/hooks/useRoute";
import { clearApiKey, getApiKey, setLandingNotice } from "@/lib/apiKey";
import { Architecture } from "@/pages/Architecture";
import { Landing } from "@/pages/Landing";

function Chat({ onLeave, onHowItWorks }: { onLeave: (notice?: string) => void; onHowItWorks: () => void }) {
  const { messages, isSending, sendMessage, startNewConversation } = useChat({
    // OpenAI rejected the key mid-session (revoked, or the account ran out): send the person back to re-enter it.
    onAuthError: (message) => onLeave(message),
  });

  return (
    <TooltipProvider delayDuration={200}>
      <SidebarProvider>
        <AppSidebar onNewChat={startNewConversation} hasMessages={messages.length > 0} onChangeKey={() => onLeave()} onHowItWorks={onHowItWorks} />
        <SidebarInset>
          <ChatView messages={messages} isSending={isSending} onSend={sendMessage} />
        </SidebarInset>
      </SidebarProvider>
      <Toaster richColors position="top-right" />
    </TooltipProvider>
  );
}

function App() {
  const [route, navigate] = useRoute();
  const hasKey = getApiKey() !== null;

  // The chat is only reachable with a verified key; a bare /chat link goes back to the landing page.
  useEffect(() => {
    if (route === "chat" && !hasKey) navigate("landing", { replace: true });
  }, [route, hasKey, navigate]);

  const leaveChat = useCallback(
    (notice?: string) => {
      clearApiKey();
      if (notice) setLandingNotice(notice);
      navigate("landing");
    },
    [navigate],
  );

  if (route === "architecture") {
    // The explainer needs no key. "Back" returns to wherever the visitor came from: the chat if they have a key, else the landing page.
    return <Architecture onBack={() => navigate(hasKey ? "chat" : "landing")} backLabel={hasKey ? "Back to chat" : "Back to start"} onOpenChat={hasKey ? () => navigate("chat") : undefined} />;
  }
  if (route === "chat" && hasKey) return <Chat onLeave={leaveChat} onHowItWorks={() => navigate("architecture")} />;
  return <Landing onLaunch={() => navigate("chat")} onHowItWorks={() => navigate("architecture")} />;
}

export default App;
