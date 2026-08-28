# IndexTTS owner 热重载代次交接

## 现象与根因

Brain 在复盘代码提交后已安全热重载，但 `quipper.py` 是 session 级 detached 进程。新 Brain 仅执行
一次 `Popen` 就记录“owner 已拉起”；新 quipper 看到同 session 的活 `voice_quipper.lock` 后静默退出。
因此 Brain 已加载新代码，11:55 启动的旧 owner 却继续服务，`/health` 也没有新版本的
`current_phase`，整批预合成逻辑实际上未上线。

## 修复

- 只哈希 `owner_epoch.py`、`indextts_gpu.py`、`quipper.py` 三个 owner 运行文件，形成稳定代码 epoch。
  普通对局提交不会触发换代；这不是全仓指纹。
- health 回显 protocol、feature、code epoch、PID、创建 FILETIME/Unix 时间。Agent 只有看到同 session
  且 epoch 一致的 ready health 才记录成功，Popen 只记录为候选启动。
- 新候选用旧锁与 health 的精确身份请求 `/handoff`。旧 owner 原子停止接单，已接任务仍完整执行
  “全部预合成后连续播放”；队列空闲后才退出。候选还要等旧 PID 的创建身份真正消失，才占锁并加载
  CUDA 模型，因此不会形成双 owner，也不会截断正在播放的结论。
- 当前线上旧 owner 不理解新协议时不强杀、不伪造成功。首次部署通过下一次统一 Stop/Start 完成一次迁移；
  后续代码代次则可在线协作交接。

## 验证与注意事项

定向单测使用 fake engine 和内存播放回调，不加载 CUDA、不调用 TTS、不发声；覆盖 health 身份、停止接单、
忙任务排水后完整播放、过期进程身份拒绝，以及原有整批预合成顺序。`brain/selfcheck.py` 还断言 epoch
始终只覆盖上述三个文件，防止以后误扩张成全仓指纹。
