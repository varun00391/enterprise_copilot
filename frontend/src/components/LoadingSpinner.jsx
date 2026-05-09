export default function LoadingSpinner({ fullScreen = false, size = 'md' }) {
  const sizes = { sm: 'h-4 w-4', md: 'h-8 w-8', lg: 'h-12 w-12' }

  const spinner = (
    <div className={`${sizes[size]} animate-spin rounded-full border-2 border-navy-600 border-t-blue-500`} />
  )

  if (fullScreen) {
    return (
      <div className="fixed inset-0 bg-navy-800 flex items-center justify-center z-50">
        <div className="flex flex-col items-center gap-4">
          <div className="h-12 w-12 animate-spin rounded-full border-2 border-navy-600 border-t-blue-500" />
          <span className="text-gray-400 text-sm">Loading OrgMind...</span>
        </div>
      </div>
    )
  }

  return spinner
}
