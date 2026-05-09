import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Mic, MicOff, Volume2, Play, Pause, Brain,
  Loader2, Trash2, Plus, MessageSquare, BookOpen, FileText,
  ThumbsUp, ThumbsDown, X, Radio, PhoneOff, Phone
} from 'lucide-react'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import { useAuth } from '../context/AuthContext'
import SelectDepartmentModal from '../components/SelectDepartmentModal'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ─── VAD constants ────────────────────────────────────────────────────────────
const VAD_SPEECH_THRESHOLD = 0.018   // RMS above this = user is speaking
const VAD_SILENCE_MS = 1600          // ms of silence after speech = end of utterance
const VAD_MAX_RECORD_MS = 30_000     // safety cap per turn
const VAD_POLL_MS = 80               // how often to sample the analyser

// ─── AudioPlayer ─────────────────────────────────────────────────────────────

function AudioPlayer({ audioUrl, autoPlay = false, onEnded }) {
  const [playing, setPlaying] = useState(false)
  const audioRef = useRef(null)

  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    el.onended = () => { setPlaying(false); onEnded?.() }
    if (autoPlay) {
      el.play().then(() => setPlaying(true)).catch(() => { onEnded?.() })
    }
  }, [autoPlay, onEnded])

  const toggle = () => {
    if (!audioRef.current) return
    if (playing) { audioRef.current.pause(); setPlaying(false) }
    else { audioRef.current.play(); setPlaying(true) }
  }

  return (
    <div className="flex items-center gap-2 mt-2 rounded-lg bg-navy-800 px-3 py-2 text-sm border border-navy-600">
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
      <Volume2 className="h-3.5 w-3.5 text-blue-400 flex-shrink-0" />
      <button
        onClick={toggle}
        className="flex items-center gap-1.5 text-xs text-blue-300 hover:text-blue-200 transition-colors"
      >
        {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
        {playing ? 'Pause' : 'Play'} response
      </button>
    </div>
  )
}

// ─── Animated bars ────────────────────────────────────────────────────────────

function Bars({ color = 'blue', count = 5, active = true }) {
  return (
    <div className="flex items-end justify-center gap-[3px]" style={{ height: 28 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={clsx('w-[3px] rounded-full', color === 'red' ? 'bg-red-400' : color === 'green' ? 'bg-green-400' : 'bg-blue-400')}
          style={{
            height: active ? undefined : 5,
            animation: active ? `barPulse 0.9s ease-in-out ${i * 0.13}s infinite alternate` : 'none',
            minHeight: 5,
          }}
        />
      ))}
      <style>{`
        @keyframes barPulse { from { height: 5px; } to { height: 22px; } }
      `}</style>
    </div>
  )
}

// ─── ConfidenceBadge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }) {
  if (confidence == null) return null
  const pct = Math.round(confidence * 100)
  const cls = pct >= 80 ? 'badge-green' : pct >= 60 ? 'badge-yellow' : 'badge-red'
  return <span className={`badge ${cls}`}>{pct}% confidence</span>
}

// ─── SourcesDrawer ────────────────────────────────────────────────────────────

function SourcesDrawer({ sources, onClose }) {
  if (!sources?.length) return null
  return (
    <div className="w-72 border-l border-navy-700 bg-navy-900 flex flex-col">
      <div className="p-4 border-b border-navy-700 flex items-center justify-between">
        <h3 className="font-semibold text-sm text-white flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-blue-400" />
          Sources ({sources.length})
        </h3>
        <button onClick={onClose} className="text-gray-500 hover:text-white"><X className="w-4 h-4" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {sources.map((src, i) => (
          <div key={i} className="p-3 bg-navy-800 rounded-lg">
            <div className="flex items-start gap-2 mb-1">
              <span className="text-xs font-bold text-blue-400">[{i + 1}]</span>
              <p className="text-xs font-medium text-white">{src.doc_name}</p>
            </div>
            <p className="text-xs text-gray-400 line-clamp-3">{src.content}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── VoiceBubble ─────────────────────────────────────────────────────────────

function VoiceBubble({ msg, onShowSources, isLatest, onAudioEnded }) {
  const [feedback, setFeedback] = useState(null)
  const isUser = msg.role === 'user'

  const handleFeedback = async (rating) => {
    try { await api.post('/chat/feedback', { message_id: msg.id, rating }); setFeedback(rating) } catch {}
  }

  return (
    <div className={clsx('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={clsx(
        'w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center mt-1',
        isUser ? 'bg-blue-500' : 'bg-navy-600 border border-navy-500'
      )}>
        {isUser ? <Mic className="w-4 h-4 text-white" /> : <Brain className="w-4 h-4 text-blue-400" />}
      </div>

      <div className={clsx('max-w-[75%] space-y-1.5', isUser ? 'items-end flex flex-col' : '')}>
        <div className={clsx(
          'rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser ? 'bg-blue-500 text-white rounded-tr-sm' : 'bg-navy-700 text-gray-200 rounded-tl-sm'
        )}>
          {msg.streaming ? (
            <span>{msg.content || ''}<span className="inline-block w-0.5 h-4 bg-blue-400 animate-pulse ml-0.5 align-middle" /></span>
          ) : isUser ? (
            <span className="whitespace-pre-wrap">{msg.content}</span>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && msg.audio_url && (
          <AudioPlayer
            audioUrl={msg.audio_url}
            autoPlay={isLatest}
            onEnded={isLatest ? onAudioEnded : undefined}
          />
        )}
        {/* If no audio but it's the latest assistant message, trigger loop */}
        {!isUser && !msg.audio_url && !msg.streaming && isLatest && (
          <LatestNoAudioTrigger onEnded={onAudioEnded} />
        )}

        {!isUser && !msg.streaming && (
          <div className="flex flex-wrap items-center gap-2 px-1">
            <ConfidenceBadge confidence={msg.confidence} />
            {msg.source_chunks?.length > 0 && (
              <button
                onClick={() => onShowSources?.(msg.source_chunks)}
                className="text-xs text-gray-500 hover:text-blue-400 flex items-center gap-1 transition-colors"
              >
                <FileText className="w-3 h-3" /> {msg.source_chunks.length} sources
              </button>
            )}
            {!feedback ? (
              <div className="flex items-center gap-1 ml-auto">
                <button onClick={() => handleFeedback('up')} className="p-1 rounded text-gray-600 hover:text-green-400 hover:bg-green-500/10 transition-colors">
                  <ThumbsUp className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => handleFeedback('down')} className="p-1 rounded text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-colors">
                  <ThumbsDown className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <span className="text-xs text-gray-600 ml-auto">{feedback === 'up' ? '👍' : '👎'}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// Fires onEnded after a short delay when there's no audio URL
function LatestNoAudioTrigger({ onEnded }) {
  useEffect(() => {
    const t = setTimeout(() => onEnded?.(), 800)
    return () => clearTimeout(t)
  }, [onEnded])
  return null
}

// ─── Main VoiceAgentPage ──────────────────────────────────────────────────────

// Conversation phases
const PHASE = {
  IDLE: 'idle',         // not in a conversation
  LISTENING: 'listening', // recording + VAD active
  PROCESSING: 'processing', // sent audio, waiting for API
  PLAYING: 'playing',   // AI audio is playing back
}

export default function VoiceAgentPage() {
  const { user, loadUser } = useAuth()
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [phase, setPhase] = useState(PHASE.IDLE)
  const [sources, setSources] = useState(null)
  const [error, setError] = useState(null)
  const [latestAiId, setLatestAiId] = useState(null)

  // Refs that must survive re-renders without causing them
  const conversationActiveRef = useRef(false)  // true while conversation loop is running
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const audioContextRef = useRef(null)
  const analyserRef = useRef(null)
  const vadTimerRef = useRef(null)         // setInterval id for VAD polling
  const silenceStartRef = useRef(null)     // when silence began
  const speechDetectedRef = useRef(false)  // has the user spoken yet this turn
  const recordStartRef = useRef(null)      // when recording started (safety cap)
  const activeSessionRef = useRef(null)    // mirror of activeSession for use inside callbacks
  const bottomRef = useRef(null)
  const noDept = !user?.dept_id

  // keep activeSessionRef in sync
  useEffect(() => { activeSessionRef.current = activeSession }, [activeSession])

  useEffect(() => { loadSessions() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // cleanup on unmount
  useEffect(() => () => stopConversation(), [])

  const loadSessions = async () => {
    try {
      const { data } = await api.get('/chat/history', {
        params: { page: 1, page_size: 50 },
      })
      setSessions(data.items || [])
    } catch {}
  }

  const loadSession = async (session) => {
    stopConversation()
    setActiveSession(session)
    setSources(null)
    setError(null)
    try {
      const { data } = await api.get(`/chat/session/${session.id}/messages`)
      setMessages(data.filter(m => m.is_voice))
    } catch { setMessages([]) }
  }

  const newConversation = () => {
    stopConversation()
    setActiveSession(null)
    setMessages([])
    setSources(null)
    setError(null)
  }

  const deleteSession = async (e, sessionId) => {
    e.stopPropagation()
    try {
      await api.delete(`/chat/session/${sessionId}`)
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (activeSession?.id === sessionId) newConversation()
    } catch {}
  }

  // ─── VAD helpers ──────────────────────────────────────────────────────────

  const stopVAD = useCallback(() => {
    if (vadTimerRef.current) {
      clearInterval(vadTimerRef.current)
      vadTimerRef.current = null
    }
    if (audioContextRef.current?.state !== 'closed') {
      audioContextRef.current?.close().catch(() => {})
      audioContextRef.current = null
      analyserRef.current = null
    }
    silenceStartRef.current = null
    speechDetectedRef.current = false
  }, [])

  const startVAD = useCallback((stream, onSilenceDetected) => {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      const source = ctx.createMediaStreamSource(stream)
      source.connect(analyser)
      audioContextRef.current = ctx
      analyserRef.current = analyser

      const buf = new Uint8Array(analyser.fftSize)
      vadTimerRef.current = setInterval(() => {
        if (!analyserRef.current) return
        analyserRef.current.getByteTimeDomainData(buf)
        // RMS energy
        let sum = 0
        for (let i = 0; i < buf.length; i++) {
          const s = (buf[i] - 128) / 128
          sum += s * s
        }
        const rms = Math.sqrt(sum / buf.length)

        if (rms > VAD_SPEECH_THRESHOLD) {
          speechDetectedRef.current = true
          silenceStartRef.current = null
        } else if (speechDetectedRef.current) {
          if (!silenceStartRef.current) silenceStartRef.current = Date.now()
          const silenceDuration = Date.now() - silenceStartRef.current
          const totalDuration = Date.now() - (recordStartRef.current || Date.now())
          if (silenceDuration >= VAD_SILENCE_MS || totalDuration >= VAD_MAX_RECORD_MS) {
            stopVAD()
            onSilenceDetected()
          }
        }
      }, VAD_POLL_MS)
    } catch (e) {
      console.warn('VAD setup failed', e)
    }
  }, [stopVAD])

  // ─── Core recording → API → loop ─────────────────────────────────────────

  const sendAudioAndContinue = useCallback(async (blob) => {
    if (!conversationActiveRef.current) return
    setPhase(PHASE.PROCESSING)

    if (blob.size < 800) {
      // Too short / silent — skip and listen again
      if (conversationActiveRef.current) startListening()
      return
    }

    const formData = new FormData()
    formData.append('file', blob, 'voice_query.webm')
    const sess = activeSessionRef.current
    if (sess?.id) formData.append('session_id', sess.id)

    const userMsgId = `vu-${Date.now()}`
    const aiMsgId = `va-${Date.now()}`
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', content: 'Transcribing…', is_voice: true, created_at: new Date().toISOString() },
      { id: aiMsgId, role: 'assistant', content: '', streaming: true, is_voice: true, confidence: null, source_chunks: null, audio_url: null, created_at: new Date().toISOString() },
    ])

    try {
      const { data } = await api.post('/voice/transcribe', formData)

      setMessages(prev => prev.map(m => {
        if (m.id === userMsgId) return { ...m, content: data.transcript }
        if (m.id === aiMsgId) return { ...m, content: data.answer_text, confidence: data.confidence, source_chunks: data.sources, audio_url: data.audio_url, streaming: false }
        return m
      }))
      setLatestAiId(aiMsgId)

      if (data.session_id && !activeSessionRef.current) {
        const s = { id: data.session_id, title: data.transcript.slice(0, 50), created_at: new Date().toISOString(), updated_at: new Date().toISOString(), message_count: 2 }
        setActiveSession(s)
        setSessions(prev => [s, ...prev])
      }

      // If no audio URL, onAudioEnded is triggered by LatestNoAudioTrigger
      // If audio URL, AudioPlayer fires onEnded → onAudioEnded
      setPhase(PHASE.PLAYING)
    } catch (err) {
      const raw = err.response?.data?.detail || ''
      // Surface quota error clearly
      const isQuota = raw.includes('limit') || raw.includes('quota') || raw.includes('funds')
      const msg = isQuota
        ? `Daily AI quota reached. Please top up your EuriAI wallet at euron.one or try again tomorrow.`
        : raw || 'Voice processing failed. Please try again.'
      setError(msg)
      setMessages(prev => prev.filter(m => m.id !== userMsgId && m.id !== aiMsgId))
      setPhase(PHASE.IDLE)
      conversationActiveRef.current = false
    }
  }, [])  // eslint-disable-line

  const startListening = useCallback(async () => {
    if (!conversationActiveRef.current) return
    setError(null)
    speechDetectedRef.current = false
    silenceStartRef.current = null

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioChunksRef.current = []
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      mr.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
      mr.start(100)
      mediaRecorderRef.current = mr
      recordStartRef.current = Date.now()
      setPhase(PHASE.LISTENING)

      startVAD(stream, () => {
        // VAD detected end-of-speech — stop recorder and send
        const recorder = mediaRecorderRef.current
        if (!recorder) return
        const ready = new Promise(res => recorder.addEventListener('stop', res, { once: true }))
        recorder.stop()
        ready.then(() => {
          recorder.stream.getTracks().forEach(t => t.stop())
          const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
          sendAudioAndContinue(blob)
        })
      })
    } catch {
      setError('Microphone access denied. Please allow microphone access.')
      setPhase(PHASE.IDLE)
      conversationActiveRef.current = false
    }
  }, [startVAD, sendAudioAndContinue])

  const onAudioEnded = useCallback(() => {
    // Called when AI audio finishes (or immediately if no audio)
    if (conversationActiveRef.current) {
      startListening()
    }
  }, [startListening])

  const startConversation = useCallback(() => {
    setError(null)
    conversationActiveRef.current = true
    startListening()
  }, [startListening])

  const stopConversation = useCallback(() => {
    conversationActiveRef.current = false
    stopVAD()
    if (mediaRecorderRef.current) {
      try { mediaRecorderRef.current.stop() } catch {}
      try { mediaRecorderRef.current.stream.getTracks().forEach(t => t.stop()) } catch {}
      mediaRecorderRef.current = null
    }
    setPhase(PHASE.IDLE)
  }, [stopVAD])

  const isActive = phase !== PHASE.IDLE

  return (
    <div className="flex h-screen bg-navy-800">
      {noDept && <SelectDepartmentModal onSuccess={() => loadUser()} />}

      {/* Session sidebar */}
      <div className="w-64 border-r border-navy-700 flex flex-col bg-navy-900">
        <div className="p-4 border-b border-navy-700">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-7 h-7 rounded-lg bg-blue-500/20 flex items-center justify-center">
              <Radio className="w-4 h-4 text-blue-400" />
            </div>
            <h2 className="text-sm font-semibold text-white">Voice Agent</h2>
          </div>
          <button
            onClick={newConversation}
            className="flex items-center gap-2 w-full px-3 py-2.5 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Session
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {sessions.length === 0 ? (
            <p className="text-xs text-gray-600 text-center py-6">No sessions yet</p>
          ) : sessions.map((s) => (
            <div key={s.id} className="relative group">
              <button
                onClick={() => loadSession(s)}
                className={clsx(
                  'w-full text-left px-3 py-2.5 rounded-lg text-xs transition-colors pr-8',
                  activeSession?.id === s.id ? 'bg-blue-500/20 text-blue-300' : 'text-gray-400 hover:bg-navy-700 hover:text-white'
                )}
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate">{s.title || 'Voice Session'}</span>
                </div>
                <p className="text-gray-600 mt-0.5 ml-5">{formatDistanceToNow(new Date(s.updated_at), { addSuffix: true })}</p>
              </button>
              <button
                onClick={(e) => deleteSession(e, s.id)}
                className="absolute right-1.5 top-2.5 p-1 rounded text-gray-600 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-col flex-1">

          {/* Header */}
          <div className="p-4 border-b border-navy-700 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-white">{activeSession?.title || 'Voice Assistant'}</h2>
              <p className="text-xs text-gray-500">
                {phase === PHASE.LISTENING && 'Listening… speak your question'}
                {phase === PHASE.PROCESSING && 'Processing your voice…'}
                {phase === PHASE.PLAYING && 'AI is responding…'}
                {phase === PHASE.IDLE && 'Press Start to begin a conversation'}
              </p>
            </div>

            {/* Phase indicator pill */}
            {isActive && (
              <div className={clsx(
                'flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium',
                phase === PHASE.LISTENING && 'bg-red-500/15 text-red-300',
                phase === PHASE.PROCESSING && 'bg-yellow-500/15 text-yellow-300',
                phase === PHASE.PLAYING && 'bg-green-500/15 text-green-300',
              )}>
                {phase === PHASE.LISTENING && <><span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />Listening</>}
                {phase === PHASE.PROCESSING && <><Loader2 className="w-3 h-3 animate-spin" />Thinking</>}
                {phase === PHASE.PLAYING && <><span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />Speaking</>}
              </div>
            )}
          </div>

          {/* Conversation */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.length === 0 && phase === PHASE.IDLE && (
              <div className="flex flex-col items-center justify-center h-full text-center gap-4">
                <div className="w-20 h-20 rounded-full bg-blue-500/10 border-2 border-blue-500/20 flex items-center justify-center">
                  <Mic className="w-9 h-9 text-blue-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white mb-1">Voice Assistant</h3>
                  <p className="text-gray-400 text-sm max-w-xs leading-relaxed">
                    Press <strong className="text-white">Start Conversation</strong> and speak naturally.<br />
                    The assistant will listen, respond, then listen again automatically.
                  </p>
                </div>
                <div className="mt-1 space-y-2 w-full max-w-xs">
                  {['What are the leave policies?', 'Summarize the Q3 report', 'How do I onboard a new hire?'].map(q => (
                    <p key={q} className="text-xs text-gray-500 italic bg-navy-700 rounded-lg px-3 py-2">"{q}"</p>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <VoiceBubble
                key={msg.id}
                msg={msg}
                onShowSources={(chunks) => setSources(chunks)}
                isLatest={msg.id === latestAiId}
                onAudioEnded={onAudioEnded}
              />
            ))}

            {/* Live listening animation */}
            {phase === PHASE.LISTENING && (
              <div className="flex flex-col items-center gap-3 py-2">
                <Bars color="red" count={7} active />
                <p className="text-xs text-red-400 font-medium">
                  Listening — I'll respond when you stop speaking
                </p>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Error banner */}
          {error && (
            <div className="mx-4 mb-2 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-2">
              <span className="text-sm text-red-300 flex-1">{error}</span>
              <button onClick={() => setError(null)} className="text-red-500 hover:text-red-300 flex-shrink-0 mt-0.5">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Bottom control bar */}
          <div className="p-6 border-t border-navy-700">
            <div className="flex flex-col items-center gap-4">

              {/* Central orb / button */}
              <div className="relative flex items-center justify-center">
                {/* Ripple rings when listening */}
                {phase === PHASE.LISTENING && (
                  <>
                    <span className="absolute w-28 h-28 rounded-full border-2 border-red-500/30 animate-ping" style={{ animationDuration: '1.4s' }} />
                    <span className="absolute w-24 h-24 rounded-full border-2 border-red-500/20 animate-ping" style={{ animationDuration: '1.0s', animationDelay: '0.3s' }} />
                  </>
                )}
                {phase === PHASE.PLAYING && (
                  <span className="absolute w-28 h-28 rounded-full border-2 border-green-500/25 animate-ping" style={{ animationDuration: '1.6s' }} />
                )}

                {/* Main button */}
                {!isActive ? (
                  <button
                    onClick={startConversation}
                    className="relative w-20 h-20 rounded-full bg-blue-500 hover:bg-blue-600 active:scale-95 flex items-center justify-center shadow-lg shadow-blue-500/30 transition-all focus:outline-none focus:ring-4 focus:ring-blue-500/40"
                  >
                    <Phone className="w-8 h-8 text-white" />
                  </button>
                ) : (
                  <button
                    onClick={stopConversation}
                    className="relative w-20 h-20 rounded-full bg-red-500 hover:bg-red-600 active:scale-95 flex items-center justify-center shadow-lg shadow-red-500/30 transition-all focus:outline-none focus:ring-4 focus:ring-red-500/40"
                  >
                    <PhoneOff className="w-8 h-8 text-white" />
                  </button>
                )}
              </div>

              {/* Status label & bars */}
              <div className="flex flex-col items-center gap-1.5 min-h-[40px]">
                {phase === PHASE.IDLE && (
                  <p className="text-sm text-gray-500">Start Conversation</p>
                )}
                {phase === PHASE.LISTENING && (
                  <>
                    <Bars color="red" count={5} active />
                    <p className="text-xs text-red-400 font-medium">Listening…</p>
                  </>
                )}
                {phase === PHASE.PROCESSING && (
                  <>
                    <Loader2 className="w-5 h-5 text-yellow-400 animate-spin" />
                    <p className="text-xs text-yellow-400">Thinking…</p>
                  </>
                )}
                {phase === PHASE.PLAYING && (
                  <>
                    <Bars color="green" count={5} active />
                    <p className="text-xs text-green-400 font-medium">Speaking…</p>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {sources && <SourcesDrawer sources={sources} onClose={() => setSources(null)} />}
      </div>
    </div>
  )
}
