"""日常搜索替换适配器：保留旧 API 工具实现，不做隐式回退。"""
import json
from yuiro.tools.netease_tool import NeteaseSearchTool
from yuiro.netease import official_client


class NeteaseClientSearchTool(NeteaseSearchTool):
    requires_env = None
    description = ('在 Windows 网易云官方客户端内搜索单曲，读取当前查询的真实标题、歌手和歌曲 ID，'
                   '不依赖 ncm-cli/开放平台。最多返回综合搜索里可见的 6 首单曲；用户在结果卡点击网易云播放。'
                   '不支持时明确失败，不更换检索后端，不自动播放或替换版本。')

    def __init__(self, identity_getter=None):
        super().__init__()
        self._identity_getter = identity_getter

    async def run(self, args: dict, task_id: str) -> str:
        try:
            if self._identity_getter is None:
                raise RuntimeError('客户端搜索未绑定角色会话')
            identity = self._identity_getter(task_id)
            result = await official_client.search(str(args.get('keyword') or ''), identity,
                                                  max(1,min(6,int(args.get('limit') or 6))))
            if self._identity_getter(task_id) != identity:
                raise RuntimeError('角色身份已变化，旧搜索结果已丢弃')
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({'status':'error','source':'netease_client_ui',
                               'message':str(exc),'fallback':False},ensure_ascii=False)


class NeteaseClientRecommendTool(NeteaseClientSearchTool):
    name = 'netease_recommend'
    description = '打开网易云官方客户端每日推荐，随机抽取当前已加载的最多6首歌曲展示结果卡。不会自动播放，不切换随机播放模式；用户点选后才播放。不使用 CLI/API 回退。'

    def schema(self):
        return {'type':'function','function':{'name':self.name,'description':self.description,'parameters':{'type':'object','properties':{'limit':{'type':'integer','minimum':1,'maximum':6}}}}}

    async def run(self,args,task_id):
        try:
            identity=self._identity_getter(task_id)
            result=await official_client.search('',identity,int(args.get('limit') or 6),daily=True)
            if self._identity_getter(task_id)!=identity:
                raise RuntimeError('角色已变化，旧推荐已丢弃')
            return json.dumps(result,ensure_ascii=False)
        except Exception as exc:
            return json.dumps({'status':'error','message':str(exc),'fallback':False},ensure_ascii=False)


class NeteaseClientFavoriteTool(NeteaseClientSearchTool):
    name='netease_favorite'
    effect='external'
    description='按用户明确要求喜欢或取消喜欢当前角色拥有的网易云正在播放/暂停歌曲。必须提供目标liked布尔状态；用户说“喜欢这首/取消喜欢”时省略song_id，由引擎核验当前角色拥有的歌曲ID；未读回确认不能宣称成功，不操作其他角色或用户手动切换的歌曲。'

    def schema(self):
        return {'type':'function','function':{'name':self.name,'description':self.description,'parameters':{'type':'object','properties':{'song_id':{'type':'string'},'liked':{'type':'boolean'}},'required':['liked']}}}

    async def run(self,args,task_id):
        try:
            identity=self._identity_getter(task_id)
            result=await official_client.favorite_owned(str(args.get('song_id') or ''),args.get('liked'),identity)
            if self._identity_getter(task_id)!=identity:
                raise RuntimeError('角色已变化，旧收藏结果已丢弃')
            return json.dumps({'status':'ok','state':result},ensure_ascii=False)
        except Exception as exc:
            return json.dumps({'status':'error','message':str(exc),'fallback':False},ensure_ascii=False)
