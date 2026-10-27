import { getServiceUrl } from '../api';
import RequestService from '../httpRequest';

export default {
    // 获取设备任务清单镜像与状态（含 deviceOnline/pending 徽标数据）
    getTodoList(macAddress, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/todo-list?macAddress=${encodeURIComponent(macAddress)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .fail((err) => {
                RequestService.clearRequestTime()
                callback(err)
            })
            .networkFail(() => {
                RequestService.reAjaxFun(() => {
                    this.getTodoList(macAddress, callback)
                })
            }).send()
    },

    // 整表保存（>30 条服务端拒绝；保存成功置待下发，60s 循环送达设备；设备级配置随整表一并提交）
    saveTodoList(data, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/todo-list`)
            .method('PUT')
            .data(data)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .fail((err) => {
                RequestService.clearRequestTime()
                callback(err)
            }).send()
    },

    // 查询每日任务模板（四组，按保存顺序；#33 每天 0 点重建当日清单的种子）
    getDailyTemplates(macAddress, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/todo-list/daily?macAddress=${encodeURIComponent(macAddress)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .fail((err) => {
                RequestService.clearRequestTime()
                callback(err)
            })
            .networkFail(() => {
                RequestService.reAjaxFun(() => {
                    this.getDailyTemplates(macAddress, callback)
                })
            }).send()
    },

    // 整组保存每日任务模板（全量替换；空文本剔除、单条 30 字截断、≤30 条）
    saveDailyTemplates(data, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/todo-list/daily`)
            .method('PUT')
            .data(data)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .fail((err) => {
                RequestService.clearRequestTime()
                callback(err)
            }).send()
    }
}
