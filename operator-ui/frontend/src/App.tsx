// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { PanelLeft } from "lucide-react";
import { useState } from "react";
import { AutonomyPanel } from "@/components/autonomy/AutonomyPanel";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AppFooter } from "@/components/layout/AppFooter";
import { AppHeader } from "@/components/layout/AppHeader";
import { LearnCard } from "@/components/learning/LearnCard";
import { LearnDialog } from "@/components/learning/LearnDialog";
import { ServicesPanel } from "@/components/services/ServicesPanel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Toaster } from "@/components/ui/sonner";
import { useChat } from "@/hooks/use-chat";
import { useAutonomy } from "@/hooks/use-autonomy";
import { useLearning } from "@/hooks/use-learning";
import { useServices } from "@/hooks/use-services";

const MAX_REASON_CHARS = 500;

export default function App() {
  const services = useServices();
  const chat = useChat();
  const autonomy = useAutonomy(chat.addError);
  const learning = useLearning(chat.addError);
  const [sheetOpen, setSheetOpen] = useState(false);

  const refreshAll = () => {
    void services.refresh();
    void autonomy.refresh();
    void learning.refresh();
  };
  // A rejection reason is journaled with the event so the learner can learn from it.
  const decide = (id: string, decision: "approve" | "reject") => {
    let reason = "";
    if (decision === "reject") {
      const answer = window.prompt("Why reject? (optional — Hermes learns from this)", "");
      if (answer === null) return;
      reason = answer.trim().slice(0, MAX_REASON_CHARS);
    }
    void autonomy.decide(id, decision, reason).then(() => learning.refresh());
  };
  const panel = (
    <ServicesPanel phase={services.phase} servers={services.servers} statuses={services.statuses} error={services.error} onRefresh={refreshAll} />
  );

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <a href="#chat-title" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Skip to chat
      </a>
      <AppHeader
        servicesTrigger={
          <Button variant="outline" size="sm" className="md:hidden" onClick={() => setSheetOpen(true)} aria-label="Open services">
            <PanelLeft aria-hidden /> Services
          </Button>
        }
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-[220px_minmax(0,1fr)_300px] md:overflow-hidden lg:grid-cols-[280px_minmax(0,1fr)_350px]">
        <aside aria-label="Services" className="hidden min-h-0 border-r bg-card md:block">{panel}</aside>
        <div className="flex min-h-[28rem] min-w-0 flex-col md:min-h-0">
          <ChatPanel
            messages={chat.messages}
            status={chat.status}
            send={chat.send}
            onNewChat={() => void chat.reset()}
            linkedEvent={learning.linkedEvent}
            onDismissEvent={learning.dismissEvent}
          />
        </div>
        <aside aria-label="Autonomy" className="min-h-[16rem] border-t bg-card md:min-h-0 md:border-t-0 md:border-l">
          <AutonomyPanel
            data={autonomy.data}
            phase={autonomy.phase}
            error={autonomy.error}
            fetchedAt={autonomy.fetchedAt}
            busy={autonomy.busy}
            onDecide={decide}
            learning={
              learning.status ? (
                <LearnCard
                  status={learning.status}
                  working={learning.dialog.working}
                  onLearn={(service) => void learning.learn(service)}
                  onOpen={learning.openDialog}
                />
              ) : null
            }
          />
        </aside>
      </main>
      <AppFooter />
      <LearnDialog
        status={learning.status}
        open={learning.dialog.open}
        note={learning.dialog.note}
        working={learning.dialog.working}
        onClose={learning.closeDialog}
        onDecide={(pending, d) => void learning.decide(pending, d)}
      />
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle>Services</SheetTitle>
            <SheetDescription className="sr-only">MCP service status</SheetDescription>
          </SheetHeader>
          {panel}
        </SheetContent>
      </Sheet>
      <Toaster position="bottom-right" />
    </div>
  );
}
