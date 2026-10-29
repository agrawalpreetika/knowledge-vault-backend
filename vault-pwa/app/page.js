'use client';
import { useState } from 'react';

export default function Home() {
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);

  const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!text && !file) {
      setStatus('⚠️ Kripya text, link ya file upload karein.');
      return;
    }

    setLoading(true);
    setStatus('Categorizing & Saving to GitHub Vault...');

    const formData = new FormData();
    if (text) formData.append('text', text);
    if (file) formData.append('file', file);

    try {
      const res = await fetch(`${BACKEND_URL}/upload`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setStatus(`✅ Saved successfully to ${data.path}`);
        setText('');
        setFile(null);
      } else {
        setStatus(`❌ Error: ${data.detail || 'Upload failed'}`);
      }
    } catch (err) {
      setStatus(`❌ Network Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-900 text-white p-6 flex flex-col items-center justify-center">
      <div className="w-full max-w-md bg-slate-800 p-6 rounded-2xl shadow-xl border border-slate-700">
        <h1 className="text-2xl font-bold text-center mb-6 text-emerald-400">📦 Knowledge Vault PWA</h1>

        <form onSubmit={handleUpload} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Text Note / Link</label>
            <textarea
              rows="4"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste LinkedIn post link, web URL, or notes here..."
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm focus:outline-none focus:border-emerald-500 text-slate-200"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Screenshot / PDF</label>
            <input
              type="file"
              accept="image/*,application/pdf"
              onChange={(e) => setFile(e.target.files[0])}
              className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-emerald-500 file:text-slate-900 hover:file:bg-emerald-400"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-bold py-3 rounded-lg transition duration-200 disabled:opacity-50"
          >
            {loading ? 'Processing...' : 'Save to GitHub Vault 🚀'}
          </button>
        </form>

        {status && (
          <div className="mt-4 p-3 bg-slate-900 border border-slate-700 rounded-lg text-xs text-center break-all text-slate-300 font-mono">
            {status}
          </div>
        )}
      </div>
    </main>
  );
}