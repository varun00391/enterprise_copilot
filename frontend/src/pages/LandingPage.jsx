import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Brain, FileText, MessageSquare, Mic, Shield, BarChart3,
  Building2, ArrowRight, ChevronRight, Star, Upload, Search,
  Zap, Lock, Users, CheckCircle
} from 'lucide-react'

function Particle({ style }) {
  return (
    <div
      className="absolute rounded-full bg-blue-500/20 animate-pulse-slow"
      style={style}
    />
  )
}

function ParticleField() {
  const particles = Array.from({ length: 30 }, (_, i) => ({
    id: i,
    style: {
      width: `${Math.random() * 6 + 2}px`,
      height: `${Math.random() * 6 + 2}px`,
      top: `${Math.random() * 100}%`,
      left: `${Math.random() * 100}%`,
      animationDelay: `${Math.random() * 3}s`,
      animationDuration: `${Math.random() * 4 + 2}s`,
    },
  }))
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((p) => <Particle key={p.id} style={p.style} />)}
    </div>
  )
}

const features = [
  {
    icon: FileText,
    title: 'Multimodal Ingestion',
    desc: 'Ingest PDFs, DOCX, spreadsheets, images, audio, and more — processed autonomously by AI agents.',
  },
  {
    icon: MessageSquare,
    title: 'Agentic Q&A',
    desc: 'Multi-agent LangGraph architecture retrieves, reasons, and responds with source-cited answers.',
  },
  {
    icon: Mic,
    title: 'Voice Interface',
    desc: 'Ask questions with your voice. Deepgram STT + ElevenLabs TTS for natural voice interactions.',
  },
  {
    icon: Building2,
    title: 'Departmental Isolation',
    desc: 'Every department gets its own isolated namespace. Zero cross-department data leakage guaranteed.',
  },
  {
    icon: BarChart3,
    title: 'Analytics Dashboard',
    desc: 'Knowledge health scores, coverage gap reports, query analytics, and document freshness tracking.',
  },
  {
    icon: Shield,
    title: 'Enterprise Security',
    desc: 'RBAC, JWT auth, PII detection, immutable audit logs, and MinIO server-side encryption.',
  },
]

const steps = [
  { icon: Upload, label: 'Upload', desc: 'Drag & drop any document format' },
  { icon: Brain, label: 'Process', desc: 'AI agents parse, chunk & embed' },
  { icon: Search, label: 'Ask', desc: 'Query in natural language' },
  { icon: Zap, label: 'Answer', desc: 'Get cited, confident answers' },
]

const useCases = [
  { dept: 'HR', color: 'from-purple-500/20 to-purple-600/10', border: 'border-purple-500/30', title: 'HR Policies', desc: 'Instantly answer employee questions about benefits, leave policies, and onboarding procedures.' },
  { dept: 'Finance', color: 'from-green-500/20 to-green-600/10', border: 'border-green-500/30', title: 'Financial Intelligence', desc: 'Query financial reports, budgets, and compliance documents in seconds — not hours.' },
  { dept: 'Legal', color: 'from-amber-500/20 to-amber-600/10', border: 'border-amber-500/30', title: 'Legal Research', desc: 'Navigate contracts, regulations, and case files with AI-powered legal document search.' },
  { dept: 'Engineering', color: 'from-blue-500/20 to-blue-600/10', border: 'border-blue-500/30', title: 'Technical Knowledge', desc: 'Search API docs, runbooks, and architecture decisions without leaving your workflow.' },
]

export default function LandingPage() {
  const [scrollY, setScrollY] = useState(0)

  useEffect(() => {
    const handle = () => setScrollY(window.scrollY)
    window.addEventListener('scroll', handle, { passive: true })
    return () => window.removeEventListener('scroll', handle)
  }, [])

  return (
    <div className="min-h-screen bg-navy-800 text-white">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-navy-700/50 backdrop-blur-md bg-navy-800/80">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold">OrgMind</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm text-gray-400">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-white transition-colors">How It Works</a>
            <a href="#use-cases" className="hover:text-white transition-colors">Use Cases</a>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login" className="btn-ghost text-sm">Sign In</Link>
            <Link to="/register" className="btn-primary text-sm">Get Started</Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section
        className="relative min-h-screen flex items-center justify-center overflow-hidden pt-16"
        style={{
          background: 'linear-gradient(135deg, #060a1a 0%, #0a0f2c 40%, #0d1b6e 100%)',
          transform: `translateY(${scrollY * 0.3}px)`,
        }}
      >
        <ParticleField />
        <div className="absolute inset-0 bg-gradient-to-b from-transparent to-navy-800" />

        <div className="relative z-10 text-center max-w-5xl mx-auto px-6 animate-fade-in">
          <div className="inline-flex items-center gap-2 bg-blue-500/10 border border-blue-500/30 rounded-full px-4 py-1.5 text-blue-300 text-sm mb-8">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            Now in Beta · Phase 1 Foundation Release
          </div>

          <h1 className="text-5xl md:text-7xl font-bold leading-tight mb-6">
            Your Organisation's{' '}
            <span className="text-gradient">AI Brain</span>
          </h1>

          <p className="text-xl md:text-2xl text-gray-400 max-w-3xl mx-auto mb-10 leading-relaxed">
            OrgMind gives every department an isolated, AI-powered knowledge base.
            Upload any document. Ask any question. Get cited answers in seconds.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
            <Link
              to="/register"
              className="flex items-center gap-2 bg-blue-500 hover:bg-blue-600 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-all duration-200 glow-blue"
            >
              Get Started Free
              <ArrowRight className="w-5 h-5" />
            </Link>
            <button className="flex items-center gap-2 border border-navy-600 text-gray-300 hover:border-blue-500 hover:text-white font-semibold px-8 py-4 rounded-xl text-lg transition-all duration-200">
              Request Demo
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>

          <div className="flex items-center justify-center gap-8 text-sm text-gray-500">
            {['No credit card required', 'Departmental isolation', '99% uptime SLA'].map((t) => (
              <div key={t} className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-blue-500" />
                {t}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Everything your enterprise knowledge needs
            </h2>
            <p className="text-gray-400 text-lg max-w-2xl mx-auto">
              Built on a multi-agent architecture with LangChain and LangGraph, OrgMind handles your entire knowledge lifecycle autonomously.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="card-hover group">
                <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center mb-4 group-hover:bg-blue-500/30 transition-colors">
                  <Icon className="w-5 h-5 text-blue-400" />
                </div>
                <h3 className="text-lg font-semibold mb-2">{title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-24 px-6 bg-navy-900/50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">How OrgMind works</h2>
            <p className="text-gray-400 text-lg">From upload to answer in under 5 seconds</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 relative">
            <div className="hidden md:block absolute top-8 left-1/4 right-1/4 h-0.5 bg-gradient-to-r from-blue-500/0 via-blue-500/50 to-blue-500/0" />
            {steps.map(({ icon: Icon, label, desc }, i) => (
              <div key={label} className="flex flex-col items-center text-center">
                <div className="relative mb-4">
                  <div className="w-16 h-16 rounded-2xl bg-blue-500/20 border border-blue-500/30 flex items-center justify-center glow-blue">
                    <Icon className="w-7 h-7 text-blue-400" />
                  </div>
                  <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-blue-500 text-white text-xs font-bold flex items-center justify-center">
                    {i + 1}
                  </div>
                </div>
                <h3 className="font-semibold text-white mb-1">{label}</h3>
                <p className="text-sm text-gray-400">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Use Cases */}
      <section id="use-cases" className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Built for every department</h2>
            <p className="text-gray-400 text-lg">Departmental isolation means every team gets their own private knowledge base</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {useCases.map(({ dept, color, border, title, desc }) => (
              <div key={dept} className={`card bg-gradient-to-br ${color} border ${border} hover:scale-[1.02] transition-transform duration-200`}>
                <div className="flex items-start justify-between mb-3">
                  <span className="text-2xl font-bold text-white">{dept}</span>
                  <span className="badge bg-white/10 text-white/70 text-xs">{dept} Department</span>
                </div>
                <h3 className="text-lg font-semibold mb-2">{title}</h3>
                <p className="text-gray-400 text-sm">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6 bg-gradient-to-r from-blue-600/20 to-navy-900/50 border-y border-blue-500/20">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Ready to unlock your organisation's knowledge?
          </h2>
          <p className="text-gray-400 text-lg mb-8">
            Deploy OrgMind in minutes with Docker Compose. Free for up to 2 departments in Phase 1.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/register" className="btn-primary text-base px-8 py-3">
              Start for Free
            </Link>
            <Link to="/admin/login" className="btn-secondary text-base px-8 py-3">
              Admin Portal
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-6 border-t border-navy-700">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-blue-500 flex items-center justify-center">
              <Brain className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-bold">OrgMind</span>
            <span className="text-gray-500 text-sm ml-2">© 2026</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-gray-500">
            <a href="#" className="hover:text-white transition-colors">Privacy Policy</a>
            <a href="#" className="hover:text-white transition-colors">Terms of Service</a>
            <a href="#" className="hover:text-white transition-colors">Contact</a>
            <a href="#" className="hover:text-white transition-colors">Documentation</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
