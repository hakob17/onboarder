package com.acme.shop

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface ShopApi {
    @POST("/api/orders")
    suspend fun placeOrder(@Body draft: OrderDraft): Order

    @GET("/api/orders/{id}")
    suspend fun getOrder(@Path("id") id: Long): Order
}
