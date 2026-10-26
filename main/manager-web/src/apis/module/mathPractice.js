import { getServiceUrl } from '../api';
import RequestService from '../httpRequest';

export default {
    // 获取设备口算练习配置（未配置返回 data=null）
    getConfig(macAddress, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/math-practice/config?macAddress=${encodeURIComponent(macAddress)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .fail((err) => {
                RequestService.clearRequestTime()
                callback(err)
            }).send()
    },

    // 保存设备口算练习配置
    saveConfig(data, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/math-practice/config`)
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

    // 分页获取设备练习记录
    getRecordList(params, callback) {
        const queryParams = new URLSearchParams({
            page: params.page,
            limit: params.pageSize,
            macAddress: params.macAddress
        }).toString();
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/math-practice/record/list?${queryParams}`)
            .method('GET')
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
