package com.pos.mobile.data.remote

import retrofit2.Response
import retrofit2.http.*

/**
 * Matches the POS backend API (FastAPI).
 * Base URL should be configurable (e.g. https://yourserver.com or http://192.168.1.x:8000).
 */
interface ApiService {

    @FormUrlEncoded
    @POST("api/auth/token")
    suspend fun login(
        @Field("username") username: String,
        @Field("password") password: String,
        @Field("grant_type") grantType: String = "password"
    ): Response<TokenResponse>

    @GET("api/products")
    suspend fun getProducts(
        @Header("Authorization") token: String
    ): Response<List<ProductDto>>

    @GET("api/customers")
    suspend fun getCustomers(
        @Header("Authorization") token: String
    ): Response<List<CustomerDto>>

    @POST("api/sales")
    suspend fun createSale(
        @Header("Authorization") token: String,
        @Body body: SaleCreateDto
    ): Response<SaleReadDto>

    @POST("auth/register")
    suspend fun authRegister(@Body body: RegisterRequest): Response<AuthResponseDto>

    @POST("auth/login")
    suspend fun authLogin(@Body body: LoginEmailRequest): Response<AuthResponseDto>

    @POST("auth/refresh")
    suspend fun authRefresh(@Body body: RefreshRequest): Response<AuthResponseDto>

    @POST("auth/logout")
    suspend fun authLogout(@Body body: LogoutRequest): Response<Map<String, Boolean>>

    @GET("auth/verify")
    suspend fun authVerify(@Header("Authorization") bearer: String): Response<VerifyResponseDto>

    @POST("auth/forgot-password")
    suspend fun authForgotPassword(@Body body: ForgotPasswordRequest): Response<OkMessageResponse>

    @POST("auth/reset-password")
    suspend fun authResetPassword(@Body body: ResetPasswordRequest): Response<Map<String, Boolean>>
}

data class TokenResponse(
    val access_token: String,
    val token_type: String = "bearer",
    val username: String? = null,
    val role: String? = null
)

data class OkMessageResponse(
    val ok: Boolean = false,
    val message: String? = null,
)

data class RegisterRequest(
    val business_name: String,
    val owner_name: String,
    val phone: String,
    val email: String,
    val password: String,
)

data class LoginEmailRequest(
    val email: String,
    val password: String,
)

data class RefreshRequest(val refresh_token: String)

data class LogoutRequest(val refresh_token: String?)

data class ForgotPasswordRequest(val email: String)

data class ResetPasswordRequest(
    val token: String,
    val new_password: String,
)

data class AuthResponseDto(
    val access_token: String,
    val refresh_token: String,
    val token_type: String = "bearer",
    val expires_in: Int = 0,
    val user_id: Int,
    val tenant_id: Int?,
    val tenant_uid: String?,
    val username: String,
    val role: String,
    val subscription_status: String,
    val trial_ends_at: String?,
    val last_verified_at: String?,
)

data class VerifyResponseDto(
    val valid: Boolean,
    val user_id: Int? = null,
    val tenant_id: Int? = null,
    val tenant_uid: String? = null,
    val subscription_status: String? = null,
    val trial_ends_at: String? = null,
    val role: String? = null,
    val username: String? = null,
    val last_verified_at: String? = null,
)

data class ProductDto(
    val id: Int,
    val name: String,
    val barcode: String?,
    val category_id: Int?,
    val stock_qty: Double,
    val selling_price: Double,
    val cost_price: Double,
    val is_active: Boolean
)

data class CustomerDto(
    val id: Int,
    val name: String,
    val phone: String?,
    val email: String?
)

data class SaleItemInputDto(
    val product_id: Int,
    val quantity: Int,
    val unit_price: Double,
    val discount: Double = 0.0
)

data class PaymentInputDto(
    val method: String,
    val amount: Double
)

data class SaleCreateDto(
    val customer_id: Int? = null,
    val items: List<SaleItemInputDto>,
    val payments: List<PaymentInputDto>,
    val notes: String? = null,
    val collection_status: String = "collected"
)

data class SaleReadDto(val id: Int, val created_at: String, val subtotal: Double, val discount_total: Double, val total: Double)
