 "use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUp,
  BusFront,
  CreditCard,
  GraduationCap,
  HeartPulse,
  Home,
  Library,
  Sparkles,
} from "lucide-react";
import { AssistantInput } from "@/components/assistant-input";
import { AssistantMessage } from "@/components/assistant-message";
import { askCampusOne, type AskResponse } from "@/lib/api";

const services = [
  {
    title: "Academics",
    description: "Courses, attendance and academic information",
    icon: GraduationCap,
    prompt: "What is the attendance criteria in bennett university?",
  },
  {
    title: "Fees",
    description: "Tuition, hostel and payment information",
    icon: CreditCard,
    prompt: "What are the B.Tech fee structure and charges?",
  },
  {
    title: "Hostel",
    description: "Accommodation and hostel facilities",
    icon: Home,
    prompt: "What are the facilities available in the hostels?",
  },
  {
    title: "Library",
    description: "Resources, timings and library services",
    icon: Library,
    prompt: "What are the library timings and facilities?",
  },
  {
    title: "Transport",
    description: "Routes, buses and campus transport",
    icon: BusFront,
    prompt: "What transport facilities are available for students?",
  },
  {
    title: "Student Support",
    description: "Health, security and student services",
    icon: HeartPulse,
    prompt: "What medical and health facilities are available for students?",
  },
];

const suggestions = ["Hostel fees", "Wi-Fi help", "Library", "Transport"];

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleAsk(value: string) {
    setQuestion("");
    setSubmittedQuestion(value);
    setResponse(null);
    setError("");
    setLoading(true);

    try {
      const result = await askCampusOne(value);
      setResponse(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong while contacting CampusOne.",
      );
    } finally {
      setLoading(false);
    }
  }

  function resetConversation() {
    setResponse(null);
    setSubmittedQuestion("");
    setQuestion("");
    setError("");
  }

  const conversationStarted = Boolean(
    submittedQuestion || response || loading || error,
  );

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#f5f5f7] text-[#111]">
      {/* Ambient liquid background */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <motion.div
          animate={{
            x: [0, 80, -30, 0],
            y: [0, -30, 40, 0],
            scale: [1, 1.08, 0.96, 1],
          }}
          transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -left-40 -top-40 h-[620px] w-[620px] rounded-full bg-blue-300/20 blur-[130px]"
        />
        <motion.div
          animate={{
            x: [0, -60, 30, 0],
            y: [0, 40, -20, 0],
            scale: [1, 0.95, 1.08, 1],
          }}
          transition={{ duration: 24, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -right-40 top-10 h-[600px] w-[600px] rounded-full bg-violet-300/15 blur-[140px]"
        />
        <motion.div
          animate={{ x: [0, 40, -30, 0], y: [0, -20, 30, 0] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
          className="absolute bottom-[-300px] left-[30%] h-[650px] w-[650px] rounded-full bg-cyan-200/15 blur-[150px]"
        />
        <div className="absolute inset-0 bg-white/30" />
        <div className="noise" />
      </div>

      {/* Navigation */}
      <nav className="relative z-20 mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <button
          onClick={resetConversation}
          className="glass flex items-center gap-3 rounded-[18px] px-3 py-2.5 text-left"
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-[12px] bg-black text-white shadow-lg">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="pr-2">
            <div className="text-[15px] font-semibold tracking-[-0.03em]">
              CampusOne
            </div>
            <div className="text-[10px] text-black/40">
              Bennett University
            </div>
          </div>
        </button>

        <div className="glass hidden items-center gap-1 rounded-full p-1.5 md:flex">
          <button className="rounded-full bg-white px-4 py-2 text-[13px] font-medium shadow-sm">
            Assistant
          </button>
          <button
            onClick={() =>
              document
                .getElementById("services")
                ?.scrollIntoView({ behavior: "smooth" })
            }
            className="rounded-full px-4 py-2 text-[13px] text-black/45 transition hover:bg-white/50 hover:text-black"
          >
            Services
          </button>
          <button className="rounded-full px-4 py-2 text-[13px] text-black/45 transition hover:bg-white/50 hover:text-black">
            About
          </button>
        </div>

        <button className="glass rounded-full px-4 py-2.5 text-[13px] font-medium transition hover:bg-white/70">
          Student Portal
        </button>
      </nav>

      <AnimatePresence mode="wait">
        {!conversationStarted ? (
          <motion.div
            key="landing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, y: -15 }}
            transition={{ duration: 0.35 }}
          >
            <section className="relative z-10 mx-auto flex max-w-6xl flex-col items-center px-5 pb-12 pt-20 text-center sm:px-8 lg:pt-24">
              <motion.div
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                className="glass-strong inline-flex items-center gap-2 rounded-full px-4 py-2 text-[12px] font-medium text-black/55"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Intelligent campus assistant
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-7 max-w-4xl text-[48px] font-semibold leading-[0.98] tracking-[-0.065em] sm:text-[64px] lg:text-[78px]"
              >
                One front door
                <br />
                <span className="text-black/35">
                  for everything on campus.
                </span>
              </motion.h1>

              <motion.p
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className="mt-6 max-w-xl text-[14px] leading-6 text-black/45 sm:text-[15px]"
              >
                Ask about academics, fees, hostels, transport, library,
                student services and more — with answers grounded in official
                Bennett University information.
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.18 }}
                className="mt-8 w-full max-w-3xl"
              >
                <AssistantInput
                  value={question}
                  onChange={setQuestion}
                  onSubmit={handleAsk}
                />
              </motion.div>

              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {suggestions.map((item) => (
                  <button
                    key={item}
                    onClick={() => handleAsk(item)}
                    className="rounded-full border border-white/70 bg-white/35 px-3 py-1.5 text-[11px] text-black/45 backdrop-blur-xl transition hover:bg-white/70 hover:text-black/70"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </section>

            <section
              id="services"
              className="relative z-10 mx-auto max-w-6xl px-5 pb-20 sm:px-8"
            >
              <div className="mb-5 flex items-end justify-between">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-black/30">
                    Explore
                  </p>
                  <h2 className="mt-1.5 text-[22px] font-semibold tracking-[-0.035em]">
                    Campus services
                  </h2>
                </div>
                <span className="hidden text-[12px] text-black/30 sm:block">
                  Everything in one place
                </span>
              </div>

              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                {services.map((service, index) => {
                  const Icon = service.icon;

                  return (
                    <motion.button
                      key={service.title}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.25 + index * 0.04 }}
                      whileHover={{ y: -3 }}
                      onClick={() => handleAsk(service.prompt)}
                      className="glass group rounded-[22px] p-4.5 text-left transition duration-300 hover:bg-white/65"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex h-10 w-10 items-center justify-center rounded-[13px] border border-white/80 bg-white/65 shadow-sm">
                          <Icon className="h-[18px] w-[18px] text-black/60" />
                        </div>
                        <ArrowUp className="h-3.5 w-3.5 rotate-45 text-black/15 transition group-hover:text-black/45" />
                      </div>
                      <h3 className="mt-4 text-[14px] font-semibold">
                        {service.title}
                      </h3>
                      <p className="mt-1 text-[12px] leading-5 text-black/40">
                        {service.description}
                      </p>
                    </motion.button>
                  );
                })}
              </div>
            </section>
          </motion.div>
        ) : (
          <motion.section
            key="conversation"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            className="relative z-10 mx-auto w-full max-w-3xl px-5 pb-20 pt-12 sm:px-8 lg:pt-20"
          >
            <div className="mb-8 text-center">
              <div className="inline-flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-black/30">
                <Sparkles className="h-3.5 w-3.5" />
                CampusOne Assistant
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl">
                Your campus, simplified.
              </h1>
            </div>

            <div className="space-y-3">
              <motion.div
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                className="ml-auto max-w-[85%] rounded-[24px] rounded-br-[8px] border border-white/80 bg-white/55 px-5 py-4 text-[14px] leading-6 text-black/65 shadow-[0_15px_45px_rgba(0,0,0,0.05)] backdrop-blur-xl"
              >
                {submittedQuestion}
              </motion.div>

              {loading && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="glass-strong flex items-center gap-3 rounded-[24px] px-5 py-4"
                >
                  <div className="flex h-8 w-8 items-center justify-center rounded-[11px] bg-black text-white">
                    <Sparkles className="h-3.5 w-3.5" />
                  </div>
                  <div>
                    <div className="text-[13px] font-medium">CampusOne</div>
                    <div className="mt-0.5 text-[11px] text-black/35">
                      Understanding your request and finding grounded
                      information...
                    </div>
                  </div>
                </motion.div>
              )}

              {response && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <AssistantMessage response={response} />
                </motion.div>
              )}

              {error && (
                <div className="glass-strong rounded-[24px] border border-red-200/60 px-5 py-4 text-[13px] leading-6 text-red-700/70">
                  {error}
                </div>
              )}
            </div>

            <div className="mt-5">
              <AssistantInput
                value={question}
                onChange={setQuestion}
                onSubmit={handleAsk}
                loading={loading}
                compact
              />
            </div>

            <button
              onClick={resetConversation}
              className="mx-auto mt-5 block text-[11px] text-black/30 transition hover:text-black/60"
            >
              ← Back to CampusOne
            </button>
          </motion.section>
        )}
      </AnimatePresence>

      <footer className="relative z-10 border-t border-black/5 px-5 py-7 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-col justify-between gap-2 text-[10px] text-black/25 sm:flex-row">
          <span>CampusOne · Bennett University</span>
          <span>Understand · Route · Ground · Resolve</span>
        </div>
      </footer>
    </main>
  );
}
