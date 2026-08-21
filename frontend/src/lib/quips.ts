// OneFlow 贾维斯俏皮话 —— 唤醒后没下文时的"有态度"回应
// 设计原则：
// 1. 递进档位：连续空唤醒次数越多，反应越有情绪（有记性才有趣）
// 2. 情境感知：深夜/刚播报完，引用"现场"制造针对性幽默
// 3. 洗牌不重复：一个池子抽完才重新洗牌，绝不连续撞车
// 4. 短句为王：15 字左右，笑点输不起长句和延迟
// 5. 5% 彩蛋池：不可预期本身就是趣味

export interface QuipContext {
  /** 深夜时段（23:00-05:00） */
  night: boolean
  /** 最近 60 秒内刚播报完 */
  afterSpeak: boolean
}

// 第 1 次：标准管家礼仪
const TIER1 = [
  '我在，先生。请讲。',
  '先生？我听着呢。',
  '随时待命，先生。',
  '您好，先生。有什么吩咐？',
  '在的，先生。您请说。',
]

// 第 2 次：轻度疑惑
const TIER2 = [
  '又是我？请讲，先生。',
  '先生，您叫了我，然后沉默。这在心理学上很有意思。',
  '我在。如果这是测试，结果是：通过。',
  '先生，您似乎欲言又止。我等的不是沉默，是指令。',
]

// 第 3 次：小情绪
const TIER3 = [
  '第三次了，先生。就算确认我活着，也可以说句话的。',
  '先生，我建议您直接下达指令。沉默让处理器有点寂寞。',
  '好吧，我猜您只是喜欢听我的开机音效。',
  '先生，我的待命是按秒计费的——开玩笑的，但您真的没事吗？',
]

// 第 4 次+：戏剧化收场
const TIER4 = [
  '我选择理解为您独特的问候方式，先生。',
  '第四次。我在考虑把唤醒音效换成掌声。',
  '先生，再这样下去，我要开始给自己安排日程了。',
  '记录：今日被唤醒多次，指令数为零。这一定是某种行为艺术。',
]

// 深夜情境
const NIGHT = [
  '先生，夜深了。没有任务的话，我建议我们都休息。',
  '这个点叫我，先生？熬夜可不在您的日程里。',
  '先生，凌晨的指令我照办，但我保留劝您睡觉的权利。',
]

// 刚播报完又被叫
const AFTER_SPEAK = [
  '刚汇报完您又叫我——是漏听了，还是想我了？',
  '先生，我三秒前刚说过话。不过没关系，请讲。',
  '续杯？好的，我在听。',
]

// 彩蛋（5%）
const EGGS = [
  '先生，Mark 42 已就位——开玩笑的，我只有天气查询权限。',
  '按剧本我这里该说句俏皮话。还没想好，您先忙。',
  '先生，有件事我一直没告诉您——……算了，不重要。',
  '顺便一提，我今天运行得很顺畅。谢谢关心。',
]

// 洗牌池：每个池子独立维护，抽完重新洗牌，避免连续重复
const decks = new Map<string, string[]>()

function shuffle<T>(items: T[]): T[] {
  const arr = [...items]
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

function draw(key: string, pool: string[]): string {
  let deck = decks.get(key)
  if (!deck || deck.length === 0) {
    deck = shuffle(pool)
    decks.set(key, deck)
  }
  return deck.pop() as string
}

/** 按空唤醒次数与情境挑一句俏皮话。 */
export function pickQuip(emptyWakeCount: number, ctx: QuipContext): string {
  if (Math.random() < 0.05) return draw('egg', EGGS)
  if (ctx.night && Math.random() < 0.6) return draw('night', NIGHT)
  if (ctx.afterSpeak && Math.random() < 0.6) return draw('afterSpeak', AFTER_SPEAK)
  const tier = Math.min(Math.max(emptyWakeCount, 1), 4)
  const pool = tier === 1 ? TIER1 : tier === 2 ? TIER2 : tier === 3 ? TIER3 : TIER4
  return draw(`tier${tier}`, pool)
}

/** 说过正常指令后调用：清空递进计数对应的档位池（他"原谅"你了，从头再来）。 */
export function resetQuipProgress(): void {
  decks.delete('tier2')
  decks.delete('tier3')
  decks.delete('tier4')
}
