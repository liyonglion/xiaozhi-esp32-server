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

    // 整表保存（>30 条服务端拒绝；保存成功置待下发，60s 循环送达设备）
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
    }
}
