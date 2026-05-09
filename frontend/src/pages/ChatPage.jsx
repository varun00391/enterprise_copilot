import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Send, Plus, MessageSquare, FileText, ChevronRight,
  ThumbsUp, ThumbsDown, Brain, User, Loader2,
  X, BookOpen, MoreVertical, Trash2, Mic, MicOff, Paperclip, Play, Pause, Volume2,
  Pencil, Check,
} from 'lucide-react'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import { useAuth } from '../context/AuthContext'
import SelectDepartmentModal from '../components/SelectDepartmentModal'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const MESSAGE_ID_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function ConfidenceBadge({ confidence }) {
  if (confidence == null) return null
  const pct = Math.round(confidence * 100)
  const color = pct >= 80 ? 'badge-green' : pct >= 60 ? 'badge-yellow' : 'badge-red'
  return <span className={`badge ${color}`}>{pct}% confidence</span>
}

function AudioPlayer({ audioUrl }) {
  const [playing, setPlaying] = useState(false)
  const audioRef = useRef(null)

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.onended = () => setPlaying(false)
    }
  }, [])

  const toggle = () => {
    if (!audioRef.current) return
    if (playing) { audioRef.current.pause(); setPlaying(false) }
    else { audioRef.current.play(); setPlaying(true) }
  }

  return (
    <div className="flex items-center gap-2 mt-2 rounded-lg bg-navy-800 px-3 py-2 text-sm">
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
      <Volume2 className="h-3.5 w-3.5 text-blue-400" />
      <button onClick={toggle} className="flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">
        {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
        {playing ? 'Pause' : 'Play'} audio response
      </button>
    </div>
  )
}

function FollowUpChips({ questions, onSelect }) {
  if (!questions || questions.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {questions.map((q, i) => (
        <button
          key={i}
          onClick={() => onSelect(q)}
          className="rounded-full border border-blue-500/40 bg-blue-500/10 px-3 py-1 text-xs text-blue-300 transition-colors hover:bg-blue-500/20 hover:text-blue-200"
        >
          {q}
        </button>
      ))}
    </div>
  )
}

function SourcePanel({ sources, onClose }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="w-80 border-l border-navy-700 bg-navy-900 flex flex-col">
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
            <div className="flex items-start gap-2 mb-2">
              <span className="text-xs font-bold text-blue-400 mt-0.5">[{i + 1}]</span>
              <div>
                <p className="text-xs font-medium text-white">{src.doc_name}</p>
                {src.page && <p className="text-xs text-gray-500">Page {src.page}</p>}
              </div>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed line-clamp-4">{src.content}</p>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-xs text-gray-600">Score: {src.score?.toFixed(3)}</span>
              <span className="text-xs text-gray-600">Chunk #{src.chunk_index}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function MessageBubble({
  msg,
  onFeedback,
  onFollowUp,
  onSubmitEditedQuestion,
  questionEditable,
  sending,
}) {
  const [feedback, setFeedback] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [editBusy, setEditBusy] = useState(false)
  const isUser = msg.role === 'user'

  const handleFeedback = async (rating) => {
    try {
      await api.post('/chat/feedback', { message_id: msg.id, rating })
      setFeedback(rating)
    } catch {}
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraft('')
  }

  const saveEditedQuestion = async () => {
    const next = draft.trim()
    if (!next || sending || editBusy) return
    setEditBusy(true)
    try {
      await onSubmitEditedQuestion?.(msg.id, next)
      setEditing(false)
      setDraft('')
    } catch {
      // Error message is applied to the streaming assistant bubble by the parent
    } finally {
      setEditBusy(false)
    }
  }

  return (
    <div className={clsx('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={clsx(
        'w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center mt-1',
        isUser ? 'bg-blue-500' : 'bg-navy-600 border border-navy-500'
      )}>
        {isUser
          ? (msg.is_voice ? <Mic className="w-4 h-4 text-white" /> : <User className="w-4 h-4 text-white" />)
          : <Brain className="w-4 h-4 text-blue-400" />}
      </div>

      <div className={clsx('max-w-[75%] space-y-1.5', isUser ? 'items-end flex flex-col' : 'items-start')}>
        {/* Image preview */}
        {msg.imagePreview && (
          <img src={msg.imagePreview} alt="attachment" className="mb-2 max-h-40 rounded-lg object-cover" />
        )}

        <div className={clsx(
          'rounded-2xl px-4 py-3 text-sm leading-relaxed w-full min-w-[12rem]',
          isUser ? 'bg-blue-500 text-white rounded-tr-sm' : 'bg-navy-700 text-gray-200 rounded-tl-sm'
        )}>
          {isUser && editing ? (
            <>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={!!sending || editBusy}
                className="w-full rounded-xl border border-blue-400/40 bg-blue-600/90 px-3 py-2 text-sm text-white placeholder:text-blue-200/70 focus:outline-none focus:ring-2 focus:ring-white/40 min-h-[4.5rem]"
                placeholder="Edit your question…"
              />
              <div className="flex flex-wrap justify-end gap-2 mt-2">
                <button
                  type="button"
                  disabled={!!sending || editBusy}
                  onClick={cancelEdit}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium bg-blue-700/80 hover:bg-blue-700 disabled:opacity-40"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!!sending || editBusy || !draft.trim()}
                  onClick={saveEditedQuestion}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium bg-white text-blue-600 hover:bg-blue-50 flex items-center gap-1 disabled:opacity-40"
                >
                  {editBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                  Resubmit
                </button>
              </div>
            </>
          ) : isUser ? (
            <span className="whitespace-pre-wrap text-sm">{msg.content}</span>
          ) : msg.streaming ? (
            <span className="text-sm">{msg.content}<span className="inline-block w-0.5 h-4 bg-blue-400 animate-pulse ml-0.5 align-middle" /></span>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {isUser && questionEditable && !editing && (
          <button
            type="button"
            disabled={!!sending}
            onClick={() => { setDraft(msg.content); setEditing(true) }}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-blue-200/90 hover:bg-white/15 disabled:opacity-40 transition-colors"
          >
            <Pencil className="w-3 h-3" />
            Edit
          </button>
        )}

        {/* Audio player for voice responses */}
        {!isUser && msg.audio_url && <AudioPlayer audioUrl={msg.audio_url} />}

        {!isUser && !msg.streaming && (
          <>
            <div className="flex flex-wrap items-center gap-2 px-1">
              <ConfidenceBadge confidence={msg.confidence} />
              {msg.source_chunks?.length > 0 && (
                <button
                  onClick={() => onFeedback?.('show-sources', msg.source_chunks)}
                  className="text-xs text-gray-500 hover:text-blue-400 flex items-center gap-1 transition-colors"
                >
                  <FileText className="w-3 h-3" />
                  {msg.source_chunks.length} sources
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
                <span className="text-xs text-gray-600 ml-auto">{feedback === 'up' ? '👍 Helpful' : '👎 Not helpful'}</span>
              )}
            </div>

            {/* Suggested follow-up questions */}
            <FollowUpChips questions={msg.suggested_followups} onSelect={onFollowUp} />
          </>
        )}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const { user, loadUser } = useAuth()
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sources, setSources] = useState(null)
  const [menuOpenId, setMenuOpenId] = useState(null)
  // Voice state
  const [recording, setRecording] = useState(false)
  const [voiceLoading, setVoiceLoading] = useState(false)
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  // Image attachment state
  const [attachedImage, setAttachedImage] = useState(null)   // { file, preview }
  const imageInputRef = useRef(null)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const noDept = !user?.dept_id

  const CHAT_HISTORY_PAGE_SIZE = 20
  const historyPageRef = useRef(1)
  const historyHasMoreRef = useRef(true)
  const loadingOlderRef = useRef(false)
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false)

  const loadHistoryFirstPage = async () => {
    try {
      const { data } = await api.get('/chat/history', {
        params: { page: 1, page_size: CHAT_HISTORY_PAGE_SIZE },
      })
      setSessions(data.items || [])
      historyPageRef.current = data.page ?? 1
      historyHasMoreRef.current = !!data.has_more
    } catch {
      setSessions([])
      historyHasMoreRef.current = false
    }
  }

  const loadHistoryNextPage = async () => {
    if (loadingOlderRef.current || !historyHasMoreRef.current) return
    loadingOlderRef.current = true
    setHistoryLoadingMore(true)
    try {
      const nextPage = historyPageRef.current + 1
      const { data } = await api.get('/chat/history', {
        params: { page: nextPage, page_size: CHAT_HISTORY_PAGE_SIZE },
      })
      const items = data.items || []
      historyPageRef.current = data.page ?? nextPage
      historyHasMoreRef.current = !!data.has_more
      if (items.length) setSessions((prev) => [...prev, ...items])
    } catch {
      historyHasMoreRef.current = false
    } finally {
      loadingOlderRef.current = false
      setHistoryLoadingMore(false)
    }
  }

  const handleSidebarScroll = (e) => {
    const el = e.target
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (nearBottom) loadHistoryNextPage()
  }

  useEffect(() => { loadHistoryFirstPage() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const loadSession = async (session) => {
    setActiveSession(session)
    setSources(null)
    try {
      const { data } = await api.get(`/chat/session/${session.id}/messages`)
      setMessages(data)
    } catch {
      setMessages([])
    }
  }

  const newChat = () => {
    setActiveSession(null)
    setMessages([])
    setSources(null)
    setMenuOpenId(null)
    setAttachedImage(null)
    inputRef.current?.focus()
  }

  const deleteSession = async (e, sessionId) => {
    e.stopPropagation()
    try {
      await api.delete(`/chat/session/${sessionId}`)
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (activeSession?.id === sessionId) { setActiveSession(null); setMessages([]); setSources(null) }
    } catch {}
    setMenuOpenId(null)
  }

  // ─── Image attachment ────────────────────────────────────────────────────────
  const handleImageSelect = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const preview = URL.createObjectURL(file)
    setAttachedImage({ file, preview })
    e.target.value = ''
  }

  const removeImage = () => {
    if (attachedImage?.preview) URL.revokeObjectURL(attachedImage.preview)
    setAttachedImage(null)
  }

  /** Stream response body after POST /chat/query; merges server message UUIDs once persisted. */
  async function consumeQueryStream(response, { aiMsgLocalId, userMsgLocalId, queryLabel }) {
    if (!response.ok) {
      let detail = ''
      try {
        detail = await response.text()
      } catch { /* ignore */ }
      throw new Error(detail || `Request failed (${response.status})`)
    }

    let userTrackId = userMsgLocalId ?? null

    const serverUserHdr = response.headers.get('X-User-Message-Id')
    if (serverUserHdr && userTrackId && String(userTrackId).startsWith('local-')) {
      setMessages(prev => prev.map((m) =>
        m.id === userTrackId ? { ...m, id: serverUserHdr } : m))
      userTrackId = serverUserHdr
    }

    const sessionIdHdr = response.headers.get('X-Session-Id')
    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response stream')
    }
    const decoder = new TextDecoder()
    let fullContent = ''

    let hitDone = false
    while (!hitDone) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      for (const line of text.split('\n')) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (raw === '[DONE]') {
          hitDone = true
          break
        }
        try {
          const data = JSON.parse(raw)
          if (data.type === 'token') {
            fullContent += data.content
            setMessages(prev => prev.map(m =>
              m.id === aiMsgLocalId ? { ...m, content: fullContent } : m))
          } else if (data.type === 'metadata') {
            setMessages(prev => prev.map(m =>
              m.id === aiMsgLocalId ? {
                ...m,
                content: data.answer || fullContent,
                confidence: data.confidence,
                source_chunks: data.sources,
                suggested_followups: data.suggested_followups || [],
                streaming: false,
              } : m))
            if (sessionIdHdr) {
              const newSess = {
                id: sessionIdHdr,
                title: queryLabel?.trim()
                  ? queryLabel.slice(0, 50)
                  : 'Image chat',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                message_count: 2,
              }
              setActiveSession(prev => (prev?.id ? prev : newSess))
              setSessions(sessPrev =>
                (sessPrev.some(s => String(s.id) === String(sessionIdHdr))
                  ? sessPrev
                  : [newSess, ...sessPrev]))
            }
          } else if (data.type === 'persisted') {
            setMessages(prev => prev.map((m) => {
              if (data.user_message_id && userTrackId && m.id === userTrackId && m.role === 'user') {
                return { ...m, id: data.user_message_id }
              }
              if (data.assistant_message_id && m.id === aiMsgLocalId) {
                return { ...m, id: data.assistant_message_id }
              }
              return m
            }))
            if (data.user_message_id) {
              userTrackId = data.user_message_id
            }
          }
        } catch { /* malformed line */ }
      }
    }

    setMessages(prev => prev.map(m =>
      m.id === aiMsgLocalId ? { ...m, streaming: false } : m))
  }

  const submitEditedQuestion = async (messageId, nextText) => {
    const q = typeof nextText === 'string' ? nextText.trim() : ''
    if (!q || sending) return

    const aiMsg = {
      id: `ai-${Date.now()}`,
      role: 'assistant',
      content: '',
      streaming: true,
      confidence: null,
      source_chunks: null,
      suggested_followups: null,
      created_at: new Date().toISOString(),
    }

    setMessages(prev => {
      const i = prev.findIndex(m => m.id === messageId)
      if (i < 0) return prev
      const head = prev.slice(0, i)
      const edited = { ...prev[i], content: q }
      return [...head, edited, aiMsg]
    })
    setSending(true)

    const token = localStorage.getItem('access_token')

    try {
      const response = await fetch('/api/chat/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          query: q,
          session_id: activeSession?.id || null,
          edit_message_id: messageId,
        }),
      })

      await consumeQueryStream(response, {
        aiMsgLocalId: aiMsg.id,
        userMsgLocalId: messageId,
        queryLabel: q,
      })
    } catch {
      setMessages(prev => prev.map(m =>
        m.id === aiMsg.id ? { ...m, content: 'Error: Could not reach the knowledge base.', streaming: false } : m))
      throw new Error('stream failed')
    } finally {
      setSending(false)
    }
  }

  // ─── Text + optional image send ──────────────────────────────────────────────
  const handleSend = async ({ event, query: queryOverride } = {}) => {
    event?.preventDefault()
    const queryText = typeof queryOverride === 'string' ? queryOverride.trim() : input.trim()
    if ((!queryText && !attachedImage) || sending) return

    const imageFile = attachedImage?.file || null
    const imagePreview = attachedImage?.preview || null

    const userMsg = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: queryText || '(image attached)',
      imagePreview,
      created_at: new Date().toISOString(),
    }
    if (typeof queryOverride !== 'string') {
      setInput('')
    }
    setAttachedImage(null)
    setMessages(prev => [...prev, userMsg])
    setSending(true)

    const aiMsg = {
      id: `ai-${Date.now()}`,
      role: 'assistant',
      content: '',
      streaming: true,
      confidence: null,
      source_chunks: null,
      suggested_followups: null,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, aiMsg])

    const token = localStorage.getItem('access_token')

    try {
      let response

      if (imageFile) {
        const fd = new FormData()
        fd.append('query', queryText)
        if (activeSession?.id) fd.append('session_id', activeSession.id)
        fd.append('image', imageFile, imageFile.name || 'image.jpg')
        response = await fetch('/api/chat/query', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        })
      } else {
        response = await fetch('/api/chat/query', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            query: queryText,
            session_id: activeSession?.id || null,
          }),
        })
      }

      await consumeQueryStream(response, {
        aiMsgLocalId: aiMsg.id,
        userMsgLocalId: userMsg.id,
        queryLabel: queryText,
      })
    } catch {
      setMessages(prev => prev.map(m => m.id === aiMsg.id ? { ...m, content: 'Error: Could not reach the knowledge base.', streaming: false } : m))
    } finally {
      setSending(false)
    }
  }

  // ─── Voice push-to-talk ──────────────────────────────────────────────────────
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      audioChunksRef.current = []
      mr.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
      mr.start(100)  // emit data chunks every 100ms so buffer fills progressively
      mediaRecorderRef.current = mr
      setRecording(true)
    } catch {
      alert('Microphone access denied.')
    }
  }, [])

  const stopRecordingAndSend = useCallback(async () => {
    if (!mediaRecorderRef.current) return
    setRecording(false)
    setVoiceLoading(true)

    const mr = mediaRecorderRef.current

    // Register stop listener BEFORE calling stop() to avoid the race condition
    // where ondataavailable fires before we're waiting
    const audioReady = new Promise(resolve => {
      mr.addEventListener('stop', resolve, { once: true })
    })
    mr.stop()
    await audioReady  // guaranteed: ondataavailable + onstop have both fired
    mr.stream.getTracks().forEach(t => t.stop())

    const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })

    if (blob.size < 1000) {
      // Recording too short / silent — abort silently
      setVoiceLoading(false)
      return
    }
    const formData = new FormData()
    formData.append('file', blob, 'voice_query.webm')
    if (activeSession?.id) formData.append('session_id', activeSession.id)

    // Show user bubble immediately
    const userMsg = {
      id: `voice-user-${Date.now()}`,
      role: 'user',
      content: 'Voice message (transcribing…)',
      is_voice: true,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])

    const aiMsg = {
      id: `voice-ai-${Date.now()}`,
      role: 'assistant',
      content: '',
      streaming: true,
      confidence: null,
      source_chunks: null,
      suggested_followups: null,
      is_voice: true,
      audio_url: null,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, aiMsg])

    try {
      const { data } = await api.post('/voice/transcribe', formData)

      setMessages(prev => prev.map(m =>
        m.id === userMsg.id ? { ...m, content: data.transcript } : m
      ))
      setMessages(prev => prev.map(m =>
        m.id === aiMsg.id ? {
          ...m,
          content: data.answer_text,
          confidence: data.confidence,
          source_chunks: data.sources,
          audio_url: data.audio_url,
          streaming: false,
        } : m
      ))

      if (data.session_id && !activeSession) {
        const newSess = { id: data.session_id, title: data.transcript.slice(0, 50), created_at: new Date().toISOString(), updated_at: new Date().toISOString(), message_count: 2 }
        setActiveSession(newSess)
        setSessions(prev => [newSess, ...prev])
      }
    } catch (err) {
      const detail = err.response?.data?.detail || 'Voice error. Please hold the mic, speak clearly, then release.'
      setMessages(prev => prev.map(m =>
        m.id === aiMsg.id ? { ...m, content: `⚠️ ${detail}`, streaming: false } : m
      ))
      // Remove the placeholder user bubble if no transcript was captured
      setMessages(prev => prev.filter(m => !(m.id === userMsg.id && m.content === 'Voice message (transcribing…)')))
    } finally {
      setVoiceLoading(false)
    }
  }, [activeSession])

  const handleFollowUp = (question) => {
    handleSend({ query: question })
    inputRef.current?.focus()
  }

  return (
    <div className="flex h-screen bg-navy-800" onClick={() => setMenuOpenId(null)}>
      {noDept && <SelectDepartmentModal onSuccess={() => loadUser()} />}

      {/* Sidebar */}
      <div className="w-64 border-r border-navy-700 flex flex-col bg-navy-900">
        <div className="p-3 border-b border-navy-700">
          <button onClick={newChat} className="flex items-center gap-2 w-full px-3 py-2.5 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium transition-colors">
            <Plus className="w-4 h-4" /> New Conversation
          </button>
        </div>
        <div
          className="flex-1 overflow-y-auto p-2 space-y-0.5"
          onScroll={handleSidebarScroll}
        >
          {sessions.length === 0 ? (
            <p className="text-xs text-gray-600 text-center py-6">No conversations yet</p>
          ) : sessions.map((s) => (
            <div key={s.id} className="relative group">
              <button
                onClick={() => { loadSession(s); setMenuOpenId(null) }}
                className={clsx(
                  'w-full text-left px-3 py-2.5 rounded-lg text-xs transition-colors pr-8',
                  activeSession?.id === s.id ? 'bg-blue-500/20 text-blue-300' : 'text-gray-400 hover:bg-navy-700 hover:text-white'
                )}
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate">{s.title || 'Conversation'}</span>
                </div>
                <p className="text-gray-600 mt-0.5 ml-5">{formatDistanceToNow(new Date(s.updated_at), { addSuffix: true })}</p>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === s.id ? null : s.id) }}
                className="absolute right-1.5 top-2.5 p-1 rounded text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <MoreVertical className="w-3.5 h-3.5" />
              </button>
              {menuOpenId === s.id && (
                <div className="absolute right-1 top-8 z-10 bg-navy-700 border border-navy-600 rounded-lg shadow-lg py-1 min-w-[120px]">
                  <button onClick={(e) => deleteSession(e, s.id)} className="flex items-center gap-2 w-full px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                </div>
              )}
            </div>
          ))}
          {historyLoadingMore && (
            <div className="flex justify-center py-2 border-t border-navy-800">
              <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
            </div>
          )}
        </div>
      </div>

      {/* Main chat */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-col flex-1">
          <div className="p-4 border-b border-navy-700 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-white">{activeSession?.title || 'New Conversation'}</h2>
              <p className="text-xs text-gray-500">Searching your department's knowledge base</p>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-16 h-16 rounded-2xl bg-blue-500/20 flex items-center justify-center mb-4">
                  <Brain className="w-8 h-8 text-blue-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Ask your knowledge base</h3>
                <p className="text-gray-400 text-sm max-w-sm">Type a question, use the mic to speak, or attach an image.</p>
                <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-md">
                  {['What are the leave policies?', 'Summarize the Q3 financial report', 'What does clause 5 say?', 'How do I onboard a new employee?'].map(q => (
                    <button key={q} onClick={() => setInput(q)} className="text-left p-3 bg-navy-700 hover:bg-navy-600 rounded-lg text-sm text-gray-300 hover:text-white transition-colors">
                      "{q}"
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                onFeedback={(action, data) => { if (action === 'show-sources') setSources(data) }}
                onFollowUp={handleFollowUp}
                sending={sending}
                questionEditable={
                  msg.role === 'user' &&
                  MESSAGE_ID_UUID_RE.test(String(msg.id)) &&
                  !msg.is_voice &&
                  !msg.imagePreview &&
                  msg.content !== '(image attached)'
                }
                onSubmitEditedQuestion={submitEditedQuestion}
              />
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="p-4 border-t border-navy-700">
            {/* Image preview */}
            {attachedImage && (
              <div className="mb-2 flex items-center gap-2 rounded-lg bg-navy-700 p-2">
                <img src={attachedImage.preview} alt="attached" className="h-12 w-12 rounded object-cover" />
                <span className="flex-1 text-xs text-gray-400 truncate">{attachedImage.file.name}</span>
                <button onClick={removeImage} className="text-gray-500 hover:text-red-400"><X className="h-4 w-4" /></button>
              </div>
            )}

            <form onSubmit={(e) => handleSend({ event: e })} className="flex gap-2">
              {/* Image attach button */}
              <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/jpg" className="hidden" onChange={handleImageSelect} />
              <button
                type="button"
                onClick={() => imageInputRef.current?.click()}
                disabled={sending || voiceLoading}
                title="Attach image"
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-navy-600 bg-navy-700 text-gray-400 hover:text-white hover:border-gray-500 transition-colors disabled:opacity-40"
              >
                <Paperclip className="h-4 w-4" />
              </button>

              <input
                ref={inputRef}
                className="input flex-1"
                placeholder="Ask a question… or use the mic / attach an image"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={sending || voiceLoading}
                autoFocus
              />

              {/* Voice button */}
              <button
                type="button"
                onMouseDown={startRecording}
                onMouseUp={stopRecordingAndSend}
                onTouchStart={startRecording}
                onTouchEnd={stopRecordingAndSend}
                disabled={sending || voiceLoading}
                title={recording ? 'Release to send' : 'Hold to speak'}
                className={clsx(
                  'flex h-10 w-10 items-center justify-center rounded-lg transition-colors disabled:opacity-40',
                  recording
                    ? 'bg-red-500 text-white animate-pulse'
                    : voiceLoading
                      ? 'bg-navy-700 text-yellow-400'
                      : 'border border-navy-600 bg-navy-700 text-gray-400 hover:text-white hover:border-gray-500'
                )}
              >
                {voiceLoading
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : recording
                    ? <MicOff className="h-4 w-4" />
                    : <Mic className="h-4 w-4" />}
              </button>

              <button
                type="submit"
                disabled={(!input.trim() && !attachedImage) || sending}
                className="btn-primary px-4 flex items-center gap-2"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </form>
            <p className="text-xs text-gray-600 mt-2 text-center">
              Hold mic to speak · Attach images for visual Q&A · Upload video from the Upload page for transcript + sampled-frame search · Responses cite your department's documents.
            </p>
          </div>
        </div>

        {sources && <SourcePanel sources={sources} onClose={() => setSources(null)} />}
      </div>
    </div>
  )
}
