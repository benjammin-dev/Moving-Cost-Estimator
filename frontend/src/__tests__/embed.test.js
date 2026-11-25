import { describe, it, expect, beforeAll, beforeEach } from 'vitest'

// public/embed.js is the script host sites load to auto-size the widget iframe.
describe('embed.js', () => {
  let frame

  beforeAll(async () => {
    await import('../../public/embed.js')
  })

  beforeEach(() => {
    document.body.innerHTML = ''
    frame = document.createElement('iframe')
    frame.setAttribute('data-moving-quote', '')
    frame.src = 'https://quotes.example.com/widget'
    frame.style.height = '1400px'
    document.body.appendChild(frame)
  })

  const send = (data, { source = frame.contentWindow, origin = 'https://quotes.example.com' } = {}) =>
    window.dispatchEvent(new MessageEvent('message', { data, source, origin }))

  it('resizes the iframe to the height the widget reports', () => {
    send({ type: 'moving-quote:resize', height: 1180 })
    expect(frame.style.height).toBe('1180px')
  })

  it('ignores messages from another origin', () => {
    send({ type: 'moving-quote:resize', height: 50 }, { origin: 'https://evil.example' })
    expect(frame.style.height).toBe('1400px')
  })

  it('ignores messages that did not come from a widget iframe', () => {
    send({ type: 'moving-quote:resize', height: 50 }, { source: window })
    expect(frame.style.height).toBe('1400px')
  })

  it('ignores other message types and bad heights', () => {
    send({ type: 'something-else', height: 50 })
    send({ type: 'moving-quote:resize', height: 'tall' })
    send({ type: 'moving-quote:resize', height: Infinity })
    expect(frame.style.height).toBe('1400px')
  })

  it('caps very large heights', () => {
    send({ type: 'moving-quote:resize', height: 10_000_000 })
    expect(frame.style.height).toBe('20000px')
  })
})
