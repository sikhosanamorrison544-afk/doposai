package com.pos.mobile.data.remote

import okhttp3.ResponseBody
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

    @POST("api/customers")
    suspend fun createCustomer(
        @Header("Authorization") token: String,
        @Body body: CustomerCreateDto,
    ): Response<CustomerDto>

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

    /** Full URL (base + path) for master offline cache sync. */
    @GET
    suspend fun getUrl(
        @Url url: String,
        @Header("Authorization") token: String,
    ): Response<ResponseBody>

    @HTTP(method = "POST", hasBody = true)
    suspend fun postUrl(
        @Url url: String,
        @Header("Authorization") token: String,
        @Body body: okhttp3.RequestBody,
    ): Response<ResponseBody>

    @HTTP(method = "PUT", hasBody = true)
    suspend fun putUrl(
        @Url url: String,
        @Header("Authorization") token: String,
        @Body body: okhttp3.RequestBody,
    ): Response<ResponseBody>

    // Layby
    @GET("api/layby/customers")
    suspend fun getLaybyCustomers(@Header("Authorization") token: String): Response<List<LaybyCustomerDto>>

    @POST("api/layby/customers")
    suspend fun createLaybyCustomer(
        @Header("Authorization") token: String,
        @Body body: LaybyCustomerCreateDto,
    ): Response<LaybyCustomerDto>

    @GET("api/layby/transactions")
    suspend fun getLaybyTransactions(
        @Header("Authorization") token: String,
        @Query("customer_id") customerId: Int? = null,
        @Query("status") status: String? = null,
    ): Response<List<LaybyTransactionDto>>

    @POST("api/layby/transactions")
    suspend fun createLaybyTransaction(
        @Header("Authorization") token: String,
        @Body body: LaybyTransactionCreateDto,
    ): Response<LaybyTransactionDto>

    @POST("api/layby/payments")
    suspend fun createLaybyPayment(
        @Header("Authorization") token: String,
        @Body body: LaybyPaymentCreateDto,
    ): Response<LaybyPaymentDto>

    // Withdrawals
    @POST("api/withdrawals")
    suspend fun createWithdrawal(
        @Header("Authorization") token: String,
        @Body body: WithdrawalCreateDto,
    ): Response<WithdrawalDto>

    @GET("api/withdrawals")
    suspend fun getWithdrawals(@Header("Authorization") token: String): Response<List<WithdrawalDto>>

    // Notifications
    @GET("api/notifications")
    suspend fun getNotifications(
        @Header("Authorization") token: String,
        @Query("unread_only") unreadOnly: Boolean = false,
    ): Response<List<NotificationDto>>

    @GET("api/notifications/unread-count")
    suspend fun getUnreadNotificationCount(@Header("Authorization") token: String): Response<UnreadCountDto>

    @PUT("api/notifications/{id}/read")
    suspend fun markNotificationRead(
        @Header("Authorization") token: String,
        @Path("id") id: Int,
    ): Response<Map<String, Boolean>>

    @PUT("api/notifications/mark-all-read")
    suspend fun markAllNotificationsRead(@Header("Authorization") token: String): Response<Map<String, Any>>

    // Analytics / statistics
    @GET("api/analytics/dashboard")
    suspend fun getAnalyticsDashboard(
        @Header("Authorization") token: String,
        @Query("days") days: Int = 30,
    ): Response<AnalyticsDashboardDto>

    // Subscriptions / Paynow billing
    @GET("api/subscriptions/plans")
    suspend fun getSubscriptionPlans(): Response<SubscriptionPlansResponseDto>

    @GET("api/subscriptions/status")
    suspend fun getSubscriptionStatus(@Header("Authorization") token: String): Response<SubscriptionStatusDto>

    @POST("api/payments/initiate")
    suspend fun initiateSubscriptionPayment(
        @Header("Authorization") token: String,
        @Body body: InitiateSubscriptionPaymentDto,
    ): Response<InitiatePaymentResponseDto>

    @POST("api/payments/verify")
    suspend fun verifySubscriptionPayment(
        @Header("Authorization") token: String,
        @Body body: VerifySubscriptionPaymentDto,
    ): Response<VerifyPaymentResponseDto>

    @GET("api/billing/history")
    suspend fun getBillingHistory(@Header("Authorization") token: String): Response<BillingHistoryDto>
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
    val reserved_qty: Double = 0.0,
    val selling_price: Double,
    val cost_price: Double,
    @com.google.gson.annotations.SerializedName("is_active")
    val is_active: Boolean = true,
)

data class CustomerCreateDto(
    val name: String,
    val phone: String? = null,
    val email: String? = null,
    val address: String? = null,
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

data class LaybyCustomerCreateDto(
    val name: String,
    val phone: String? = null,
    val email: String? = null,
    val address: String? = null,
    val layby_item_name: String? = null,
)

data class LaybyCustomerDto(
    val id: Int,
    val name: String,
    val phone: String? = null,
    val email: String? = null,
    val address: String? = null,
    val layby_item_name: String? = null,
    val active_items: String? = null,
)

data class LaybyTransactionCreateDto(
    val customer_id: Int,
    val product_id: Int,
    val quantity: Int = 1,
    val notes: String? = null,
)

data class LaybyTransactionDto(
    val id: Int,
    val customer_id: Int,
    val customer_name: String,
    val product_id: Int,
    val product_name: String,
    val quantity: Int,
    val unit_price: Double,
    val total_amount: Double,
    val paid_amount: Double,
    val balance: Double,
    val status: String,
)

data class LaybyPaymentCreateDto(
    val transaction_id: Int,
    val amount: Double,
    val payment_method: String,
    val notes: String? = null,
)

data class LaybyPaymentDto(
    val id: Int,
    val transaction_id: Int,
    val amount: Double,
    val payment_method: String,
    val receipt_number: String? = null,
)

data class WithdrawalCreateDto(
    val amount: Double,
    val reason: String,
    val notes: String? = null,
    val salary_details: Map<String, String>? = null,
)

data class WithdrawalDto(
    val id: Int,
    val cashier_name: String,
    val amount: Double,
    val reason: String,
    val receipt_number: String? = null,
    val notes: String? = null,
)

data class NotificationDto(
    val id: Int,
    val type: String,
    val message: String,
    val product_id: Int? = null,
    val product_name: String? = null,
    val is_read: Boolean,
)

data class UnreadCountDto(val count: Int)

data class AnalyticsDashboardDto(
    val period_days: Int,
    val top_selling: AnalyticsProductStatDto? = null,
    val least_selling: AnalyticsProductStatDto? = null,
    val summary: AnalyticsSummaryDto? = null,
)

data class AnalyticsProductStatDto(
    val product_id: Int? = null,
    val product_name: String? = null,
    val barcode: String? = null,
    val quantity_sold: Int = 0,
    val revenue: Double = 0.0,
)

data class AnalyticsSummaryDto(
    val total_revenue: Double = 0.0,
    val total_products_sold: Int = 0,
    val total_active_products: Int = 0,
    val zero_sales_count: Int = 0,
)

data class SubscriptionPlansResponseDto(
    val plans: List<SubscriptionPlanDto>,
    val paynow_configured: Boolean = false,
)

data class SubscriptionPlanDto(
    val id: String,
    val name: String,
    val monthly: PlanCycleDto? = null,
    val yearly: PlanCycleDto? = null,
)

data class PlanCycleDto(
    val amount_usd: Double,
    val label: String,
    val currency: String = "USD",
)

data class SubscriptionStatusDto(
    val tenant_id: Int,
    val tenant_uid: String?,
    val plan: String,
    val billing_cycle: String?,
    val status: String,
    val effective_status: String,
    val access_allowed: Boolean,
    val trial_end: String?,
    val subscription_end: String?,
    val days_remaining: Int? = null,
    val days_remaining_trial: Int? = null,
    val days_remaining_subscription: Int? = null,
    val offline_grace_hours: Int = 72,
)

data class InitiateSubscriptionPaymentDto(
    val plan: String,
    val billing_cycle: String,
    val ecocash_phone: String? = null,
    val channel: String = "android",
)

data class InitiatePaymentResponseDto(
    val payment_reference: String,
    val amount: Double,
    val currency: String,
    val plan: String,
    val billing_cycle: String,
    val poll_url: String?,
    val redirect_url: String?,
    val instructions: String?,
    val status: String,
)

data class VerifySubscriptionPaymentDto(
    val payment_reference: String,
    val poll_url: String? = null,
)

data class VerifyPaymentResponseDto(
    val status: String,
    val paid: Boolean = false,
    val payment_reference: String? = null,
    val effective_status: String? = null,
    val access_allowed: Boolean? = null,
)

data class BillingHistoryDto(
    val payments: List<BillingPaymentDto>,
    val events: List<BillingEventDto>,
)

data class BillingPaymentDto(
    val id: Int,
    val payment_reference: String,
    val paynow_reference: String?,
    val amount: Double,
    val currency: String,
    val status: String,
    val payment_method: String,
    val plan: String?,
    val billing_cycle: String?,
    val created_at: String,
    val paid_at: String?,
)

data class BillingEventDto(
    val id: Int,
    val event_type: String,
    val description: String?,
    val created_at: String,
)
