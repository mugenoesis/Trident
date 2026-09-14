import { useRef, useState } from 'react'

interface UploaderProps {
  onFileSelected: (file: File) => void
  fileName: string | null
  uploadStatus: 'idle' | 'uploading' | 'done' | 'error'
}

const ACCEPT = '.stl,.3mf,.obj,.step,.stp'

export default function Uploader({ onFileSelected, fileName, uploadStatus }: UploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0]
    if (file) onFileSelected(file)
  }

  return (
    <div
      className={`uploader${dragOver ? ' uploader-drag' : ''}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        handleFiles(e.dataTransfer.files)
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />
      {fileName ? (
        <>
          <strong>{fileName}</strong>
          <span className="uploader-status">
            {uploadStatus === 'uploading' && 'Uploading…'}
            {uploadStatus === 'done' && 'Ready to slice'}
            {uploadStatus === 'error' && 'Upload failed — click to retry'}
          </span>
        </>
      ) : (
        <>
          <strong>Drop an STL/3MF/OBJ/STEP here</strong>
          <span className="uploader-status">or click to choose a file</span>
        </>
      )}
    </div>
  )
}
