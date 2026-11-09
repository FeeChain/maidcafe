// Character identity comes from approved v3 art; v5 scenes reframe the room.
export const ART = {
 'haruka-room-v5.png': {name:'Haruka',role:'店长',position:'27% 32%',mobile:'18% center',room:'left center'},
 'aoi-room-v5.png': {name:'Aoi',role:'见习女仆',position:'27% 35%',mobile:'18% center',room:'left center'},
 'shizuku-room-v5.png': {name:'Shizuku',role:'厨房担当',position:'27% 32%',mobile:'18% center',room:'left center'},
 'suzu-room-v5.png': {name:'Suzu',role:'迎宾女仆',position:'27% 32%',mobile:'18% center',room:'left center'},
 'welcome-suzu-v4.png': {name:'Suzu',role:'迎宾女仆',position:'59% 40%',mobile:'58% 28%'},
 'reading-haruka-v3.webp': {name:'Haruka',role:'店长',position:'52% 35%',mobile:'52% 25%',room:'50% 30%',roomWidth:'150%',roomLeft:'-50%'},
 'tea-shizuku-v3.webp': {name:'Shizuku',role:'厨房担当',position:'44% 35%',mobile:'44% 27%'},
 'study-aoi-v3.webp': {name:'Aoi',role:'见习女仆',position:'61% 34%',mobile:'60% 27%',room:'50% 30%',roomWidth:'180%',roomLeft:'-80%'},
 'momo-room-v4.png': {name:'Momo',role:'看板娘',position:'27% 32%',mobile:'26% center',room:'50% center'},
 'rest-momo-v3.webp': {name:'Momo',role:'看板娘',position:'42% 32%',mobile:'42% 25%'},
 'rainy-table.webp': {name:'maidcafe',role:'雨天的窗边',position:'50% 50%',mobile:'50% 50%'}
};
export const POOLS = {
 start:['momo-room-v4.png'],
 methods:['haruka-room-v5.png','shizuku-room-v5.png'],
 level:['shizuku-room-v5.png','haruka-room-v5.png'],
 assessment:['aoi-room-v5.png','haruka-room-v5.png'],
 result:['momo-room-v4.png'],
 learn:['aoi-room-v5.png','haruka-room-v5.png','momo-room-v4.png','shizuku-room-v5.png','suzu-room-v5.png'],
 group:['momo-room-v4.png','shizuku-room-v5.png','haruka-room-v5.png'],
 'welcome-end':['momo-room-v4.png'],
 complete:['momo-room-v4.png','shizuku-room-v5.png'],
 library:['aoi-room-v5.png'],
 history:['haruka-room-v5.png'],
 player:['momo-room-v4.png','shizuku-room-v5.png'],
 settings:['shizuku-room-v5.png'],
 'exam-select':['suzu-room-v5.png'],
 exam:['aoi-room-v5.png'],
 'exam-result':['haruka-room-v5.png'],
 error:['rainy-table.webp']
};
export function pickArt(pool,previous,random=Math.random){const candidates=pool.filter(x=>x!==previous);const choices=candidates.length?candidates:pool;return choices[Math.floor(random()*choices.length)];}

export const PAGE_LABELS={
 boot:['P00','进店准备'],welcome:['P01','初次进店'],start:['P02','认识彼此'],
 methods:['P03','选择测试'],level:['P04','已掌握档位'],assessment:['P05','起点测试'],
 result:['P06','测试结果'],'welcome-end':['P07B','欢迎完成'],
 learn:['P08-A','学习词卡'],group:['P08-B','组末对话'],complete:['P08-C','本轮完成'],
 library:['M01','词库与生词本'],history:['M02','对话历史'],settings:['M03','设置'],
 'exam-select':['M04','选择考试范围'],exam:['M04-A','主动考试'],'exam-result':['M04-B','考试结果'],
 player:['P10','对话播放器'],error:['E01','错误恢复']
};

// Ambient café conversation, one entry per group. Never instructions to relax.
export const CAFE_LINES=[
 '今天的阳光，把窗框的影子画在了桌上。',
 '刚磨好的咖啡，总会让人想起某个早晨。',
 '窗外那棵树，好像又长出了一片新叶。',
 '我喜欢杯子碰到托盘时，那一声轻轻的响。',
 '有些故事，要等咖啡喝到一半才开始。',
 '街角的面包店，今天比我们还早开门。',
 '你听，门口的风铃又响了。',
 '我一直想知道，猫会梦见什么。',
 '雨天的玻璃，总像一张没有写完的明信片。',
 '柜台上的那束花，是今早刚换的。',
 '有时候，一首歌就能让人想起整条街。',
 '这只杯子的花纹，我已经看了好多遍。',
 '天色一暗，店里的灯就显得特别暖。',
 '我想把今天的云，画在小票背面。',
 '同一条街，早晨和傍晚像两个地方。',
 '书签夹住的那一页，还藏着昨天的故事。',
 '咖啡豆装进玻璃罐的声音，很好听。',
 '你会记得旅途中喝过的第一杯咖啡吗？',
 '窗边那盆绿植，总是朝着太阳的方向。',
 '我发现，大家搅拌咖啡的习惯都不一样。',
 '旧唱片里的沙沙声，也算音乐的一部分吧。',
 '有些地方，去过一次就能记住气味。',
 '今天的拉花，差一点就画成一只猫了。',
 '我想给每个季节，都留一张照片。',
 '远处的路灯亮了，城市又换了一种颜色。',
 '朋友推荐的那本书，我终于翻到结尾了。',
 '窗外走过的人，也都有自己的故事。',
 '有时候，熟悉的味道会先认出你。',
 '杯底留下的咖啡圈，像一枚小小的年轮。',
 '我给店里的植物起了名字，不过还没告诉她们。',
 '晴天适合开窗，雨天适合听屋檐。',
 '今天的第一位客人，带来了一把蓝色雨伞。',
 '有些话，坐在桌子的对面就比较好说。',
 '听说旧书店又来了一批旅行手记。',
 '门口的石阶，被来来往往的鞋子磨得很亮。',
 '甜点柜里最后一块蛋糕，总让我有点犹豫。',
 '我小时候，总以为咖啡只是一种香味。',
 '晚霞落在玻璃杯上，颜色会再深一点。',
 '有人喜欢记日期，有人更容易记住天气。',
 '如果能把香气寄出去，我想寄一封咖啡味的信。',
 '我们昨天争论了一整晚，哪种饼干最配咖啡。',
 '那本菜单的角落，藏着一颗小星星。',
 '一个名字被念熟以后，也会变得亲切起来。',
 '窗外的车流，听久了有点像海。',
 '我收集了几张很好看的咖啡豆包装。',
 '每次换季，我都会重新喜欢上这扇窗。',
 '某天再走回这里，也许树已经更高了。',
 '我觉得，一家店的故事是客人们一点点带来的。'
];

// 25 approved scenes: one durable choice per group, including retries.
ART['momo-morning-v6.webp']={"name": "Momo", "role": "看板娘", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['momo-rain-v6.webp']={"name": "Momo", "role": "看板娘", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['momo-night-v6.webp']={"name": "Momo", "role": "看板娘", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['momo-garden-v6.webp']={"name": "Momo", "role": "看板娘", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['haruka-morning-v6.webp']={"name": "Haruka", "role": "店长", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['haruka-rain-v6.webp']={"name": "Haruka", "role": "店长", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['haruka-night-v6.webp']={"name": "Haruka", "role": "店长", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['haruka-garden-v6.webp']={"name": "Haruka", "role": "店长", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['shizuku-morning-v6.webp']={"name": "Shizuku", "role": "厨房担当", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['shizuku-rain-v6.webp']={"name": "Shizuku", "role": "厨房担当", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['shizuku-night-v6.webp']={"name": "Shizuku", "role": "厨房担当", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['shizuku-garden-v6.webp']={"name": "Shizuku", "role": "厨房担当", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['suzu-morning-v6.webp']={"name": "Suzu", "role": "迎宾女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['suzu-rain-v6.webp']={"name": "Suzu", "role": "迎宾女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['suzu-night-v6.webp']={"name": "Suzu", "role": "迎宾女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['suzu-garden-v6.webp']={"name": "Suzu", "role": "迎宾女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['aoi-morning-v6.webp']={"name": "Aoi", "role": "见习女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['aoi-rain-v6.webp']={"name": "Aoi", "role": "见习女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['aoi-night-v6.webp']={"name": "Aoi", "role": "见习女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
ART['aoi-garden-v6.webp']={"name": "Aoi", "role": "见习女仆", "position": "27% 32%", "mobile": "18% center", "room": "left center"};
POOLS.learn.push(...Object.keys(ART).filter(k=>k.endsWith('-v6.webp')));
POOLS.group=[...POOLS.learn];
