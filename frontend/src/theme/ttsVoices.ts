// edge-tts 常用中文音色（免费无 Key），供设置页选择
export interface TtsVoiceOption {
  id: string
  label: string
  desc: string
}

export const TTS_VOICES: TtsVoiceOption[] = [
  { id: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女·温和）', desc: '默认音色，亲和自然' },
  { id: 'zh-CN-XiaoyiNeural', label: '晓伊（女·活泼）', desc: '年轻活泼' },
  { id: 'zh-CN-YunxiNeural', label: '云希（男·阳光）', desc: '青年男声' },
  { id: 'zh-CN-YunjianNeural', label: '云健（男·沉稳）', desc: '新闻播报风，最接近管家气质' },
  { id: 'zh-CN-YunyangNeural', label: '云扬（男·专业）', desc: '专业男声' },
]
